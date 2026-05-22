@echo off
cd /d "%~dp0"
echo Lancement de GuitarMultiCam Studio...
python cli\main.py gui
if %errorlevel% neq 0 (
    echo.
    echo [FAIL] PyQt6 est requis.
    echo Pour installer : python -m pip install PyQt6
    pause
)
