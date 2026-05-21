# GuitarMultiCam Studio

## Status
🟡 En développement — Phase 1: Video Analyzer (segmentation audio)

## Concept
Outil de montage vidéo assisté IA pour musiciens — analyse intelligente des rushs, sync automatique par audio fingerprinting, composition multi-cam.

## Architecture

```
src/
├── analyzer/          # Video Analyzer (Phase 1)
│   └── video_analyzer.py
├── sync/              # Audio Sync Engine
├── composer/          # Video Grid Builder
├── record/            # Capture Module (futur)
└── export/            # Render Pipeline

cli/                   # Command-line tools
gui/                   # PyQt6 Interface (Phase 2)
tests/                 # Tests unitaires
```

## Module Video Analyzer (Terminé)

### Fonctionnalités
- Extraction audio des vidéos
- Analyse MFCC (timbre, texture)
- Détection BPM/tempo
- Détection de tonalité (key)
- Onset detection (attaques musicales)
- Segmentation automatique (silence, quiet, music, loud)
- Snap des cuts sur les onsets
- Matching de clips par similarité audio

### Algorithmes utilisés
- **Cross-correlation** pour sync
- **MFCC** pour fingerprint audio
- **Energy envelope** pour segmentation
- **Onset strength** pour cuts propres

## Roadmap

- [x] Phase 1: Video Analyzer CLI
- [ ] Phase 2: Audio Sync Engine
- [ ] Phase 3: Video Composer (Grid 2x2, PIP, etc.)
- [ ] Phase 4: GUI PyQt6
- [ ] Phase 5: Record Module
- [ ] Phase 6: Export & Social

## Stack technique

| Composant | Tech |
|-----------|------|
| Analyse audio | librosa, scipy |
| Traitement vidéo | FFmpeg |
| GUI | PyQt6/PySide6 |
| Packaging | PyInstaller |

## License
À déterminer (MIT probablement pour opensource)