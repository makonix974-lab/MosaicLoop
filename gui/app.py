"""
GuitarMultiCam Studio — Minimal Tk GUI (v0.3).

A thin wrapper around the v0.2 pipeline:
  - pick clips, pick output, pick preset, click Run
  - pipeline output streams into the log panel
  - the heavy work runs on a worker thread so the window stays responsive

No new dependencies: tkinter ships with Python.
"""

from __future__ import annotations

import io
import queue
import sys
import threading
import tkinter as tk
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from pipeline import PRESETS, Pipeline, PipelineConfig  # noqa: E402

LAYOUTS = ["2x2", "2x1", "1x2", "1x1"]
PRESET_CHOICES = ["(none)"] + list(PRESETS.keys())


class _QueueWriter(io.TextIOBase):
    """File-like that pushes every chunk to a Queue (thread-safe)."""

    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, s: str) -> int:
        if s:
            self._q.put(s)
        return len(s)

    def flush(self) -> None:
        pass


class App(tk.Tk):
    POLL_MS = 80

    def __init__(self) -> None:
        super().__init__()
        self.title("GuitarMultiCam Studio — v0.3 (minimal)")
        self.geometry("780x620")
        self.minsize(640, 520)

        self._log_q: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_ui()
        self.after(self.POLL_MS, self._drain_log)

    # ---------- UI ----------

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # Clips panel
        clips_frame = ttk.LabelFrame(self, text="Clips")
        clips_frame.pack(fill="both", expand=False, **pad)

        self.clips_list = tk.Listbox(clips_frame, height=5,
                                     selectmode=tk.EXTENDED)
        self.clips_list.pack(side="left", fill="both", expand=True,
                             padx=6, pady=6)

        btns = ttk.Frame(clips_frame)
        btns.pack(side="right", fill="y", padx=6, pady=6)
        ttk.Button(btns, text="Add…", command=self._add_clips).pack(fill="x")
        ttk.Button(btns, text="Remove", command=self._remove_clip).pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="Clear", command=self._clear_clips).pack(fill="x", pady=(4, 0))

        # Options panel
        opts = ttk.LabelFrame(self, text="Options")
        opts.pack(fill="x", **pad)

        ttk.Label(opts, text="Output:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.output_var = tk.StringVar(value=str(_ROOT / "output" / "final.mp4"))
        ttk.Entry(opts, textvariable=self.output_var).grid(
            row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(opts, text="Browse…", command=self._pick_output).grid(
            row=0, column=2, padx=6, pady=4)

        ttk.Label(opts, text="Preset:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.preset_var = tk.StringVar(value="(none)")
        ttk.Combobox(opts, textvariable=self.preset_var, values=PRESET_CHOICES,
                     state="readonly", width=14).grid(
            row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(opts, text="Layout:").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.layout_var = tk.StringVar(value="2x2")
        ttk.Combobox(opts, textvariable=self.layout_var, values=LAYOUTS,
                     state="readonly", width=14).grid(
            row=2, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(opts, text="Audio source (clip #):").grid(
            row=3, column=0, sticky="w", padx=6, pady=4)
        self.audio_var = tk.IntVar(value=1)
        ttk.Spinbox(opts, from_=1, to=16, textvariable=self.audio_var,
                    width=5).grid(row=3, column=1, sticky="w", padx=6, pady=4)

        self.cache_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Use session cache",
                        variable=self.cache_var).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        opts.columnconfigure(1, weight=1)

        # Action buttons
        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        self.run_btn = ttk.Button(actions, text="Run pipeline",
                                  command=self._on_run)
        self.run_btn.pack(side="left")
        ttk.Button(actions, text="Open output folder",
                   command=self._open_output_dir).pack(side="left", padx=8)
        ttk.Button(actions, text="Clear log",
                   command=self._clear_log).pack(side="right")

        # Log panel
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(log_frame, wrap="word", height=14,
                           state="disabled", bg="#111", fg="#ddd",
                           insertbackground="#ddd")
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(log_frame, command=self.log.yview)
        sb.pack(side="right", fill="y", pady=6)
        self.log.config(yscrollcommand=sb.set)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(self, textvariable=self.status_var, anchor="w",
                  relief="sunken").pack(fill="x", side="bottom")

    # ---------- Clip list handlers ----------

    def _add_clips(self) -> None:
        files = filedialog.askopenfilenames(
            title="Select video clips",
            filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi"),
                       ("All", "*.*")])
        for f in files:
            self.clips_list.insert(tk.END, f)

    def _remove_clip(self) -> None:
        for idx in reversed(self.clips_list.curselection()):
            self.clips_list.delete(idx)

    def _clear_clips(self) -> None:
        self.clips_list.delete(0, tk.END)

    def _pick_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Output file",
            defaultextension=".mp4",
            initialfile=Path(self.output_var.get()).name,
            filetypes=[("MP4", "*.mp4")])
        if path:
            self.output_var.set(path)

    def _open_output_dir(self) -> None:
        out = Path(self.output_var.get()).parent
        out.mkdir(parents=True, exist_ok=True)
        try:
            import os
            os.startfile(str(out))  # type: ignore[attr-defined]
        except (AttributeError, OSError) as e:
            messagebox.showinfo("Output folder", f"{out}\n\n({e})")

    # ---------- Log plumbing ----------

    def _drain_log(self) -> None:
        try:
            while True:
                chunk = self._log_q.get_nowait()
                self.log.config(state="normal")
                self.log.insert(tk.END, chunk)
                self.log.see(tk.END)
                self.log.config(state="disabled")
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._drain_log)

    def _clear_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.config(state="disabled")

    # ---------- Run ----------

    def _on_run(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            messagebox.showinfo("Busy", "Pipeline already running.")
            return

        clips = list(self.clips_list.get(0, tk.END))
        if len(clips) < 2:
            messagebox.showerror("Need clips", "Add at least 2 clips.")
            return

        preset = self.preset_var.get()
        cfg = PipelineConfig(
            clips=clips,
            output_path=self.output_var.get(),
            layout=self.layout_var.get(),
            preset="" if preset == "(none)" else preset,
            audio_source=max(0, self.audio_var.get() - 1),  # UI is 1-indexed
            use_cache=self.cache_var.get(),
        )

        self.run_btn.config(state="disabled")
        self.status_var.set("Running…")
        self._clear_log()

        self._worker = threading.Thread(
            target=self._run_pipeline, args=(cfg,), daemon=True)
        self._worker.start()

    def _run_pipeline(self, cfg: PipelineConfig) -> None:
        writer = _QueueWriter(self._log_q)
        ok = False
        err: str | None = None
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                result = Pipeline(cfg).run()
            ok = bool(result.get("success"))
            err = result.get("error")
        except Exception as e:  # noqa: BLE001 — surface anything to the log
            err = f"{type(e).__name__}: {e}"
            self._log_q.put(f"\n[CRASH] {err}\n")

        def _done() -> None:
            self.run_btn.config(state="normal")
            self.status_var.set("Done" if ok else f"Failed — {err or 'see log'}")
        self.after(0, _done)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
