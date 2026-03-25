@echo off
:: setup.bat — One-shot environment bootstrap for DPP Expert 3.1 (Windows)
:: Usage: Double-click or run from Command Prompt: setup.bat

setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%.venv"

echo ========================================================
echo   DPP Expert 3.1 ^— Environment Setup (Windows)
echo   Project: %PROJECT_DIR%
echo ========================================================

:: ── 1. Check Python ────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   Detected Python %PYVER%

:: ── 2. Create virtual environment ─────────────────────────────────────────
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo.
    echo   [1/5] Creating virtual environment at .venv ...
    python -m venv "%VENV_DIR%"
) else (
    echo.
    echo   [1/5] Virtual environment already exists -- skipping.
)

call "%VENV_DIR%\Scripts\activate.bat"

:: ── 3. Upgrade pip ────────────────────────────────────────────────────────
echo.
echo   [2/5] Upgrading pip ...
pip install --quiet --upgrade pip

:: ── 4. Install dependencies ───────────────────────────────────────────────
echo.
echo   [3/5] Installing Python dependencies from requirements.txt ...
pip install --quiet -r "%PROJECT_DIR%requirements.txt"
if errorlevel 1 (
    echo   ERROR: pip install failed. Check your internet connection and try again.
    pause
    exit /b 1
)

:: ── 5. WeasyPrint notice ───────────────────────────────────────────────────
echo.
echo   [4/5] Note: WeasyPrint on Windows requires GTK3 runtime.
echo   Download from: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer
echo   WeasyPrint is OPTIONAL -- fpdf2 is the default PDF backend.

:: ── 6. Font check ─────────────────────────────────────────────────────────
echo.
echo   [5/5] Checking NotoSansSC-Regular.otf font ...
set "FONT_PATH=%PROJECT_DIR%NotoSansSC-Regular.otf"
if exist "%FONT_PATH%" (
    echo   Font already present -- skipping download.
) else (
    echo   Downloading NotoSansSC-Regular.otf ...
    set "FONT_URL=https://github.com/googlefonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf"
    powershell -Command "Invoke-WebRequest -Uri '%FONT_URL%' -OutFile '%FONT_PATH%'" 2>nul
    if exist "%FONT_PATH%" (
        echo   Font downloaded successfully.
    ) else (
        echo   WARNING: Download failed. Please download manually and place as:
        echo   %FONT_PATH%
    )
)

:: ── Summary ───────────────────────────────────────────────────────────────
echo.
echo ========================================================
echo   Setup complete!
echo.
echo   Activate the environment:
echo     .venv\Scripts\activate
echo.
echo   Run the Streamlit web UI:
echo     streamlit run app.py
echo.
echo   Run the FastAPI backend:
echo     uvicorn app.main:app --reload --port 8000
echo     Then open: http://localhost:8000/docs
echo.
echo   Run CLI audit:
echo     python dpp_engine.py --csv data\test_data.csv
echo ========================================================
pause
