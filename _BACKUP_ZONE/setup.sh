#!/usr/bin/env bash
# setup.sh — One-shot environment bootstrap for DPP Expert 3.1
# Usage: bash setup.sh
# Tested on macOS 14+ and Ubuntu 22.04+

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON="${PYTHON:-python3}"

echo "========================================================"
echo "  DPP Expert 3.1 — Environment Setup"
echo "  Project: $PROJECT_DIR"
echo "========================================================"

# ── 1. Check Python version ────────────────────────────────────────────────────
PYTHON_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

echo "  Detected Python $PYTHON_VERSION"

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; }; then
  echo "  ERROR: Python 3.10+ is required. Current: $PYTHON_VERSION"
  exit 1
fi

# ── 2. Create virtual environment ─────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
  echo ""
  echo "  [1/5] Creating virtual environment at .venv ..."
  "$PYTHON" -m venv "$VENV_DIR"
else
  echo ""
  echo "  [1/5] Virtual environment already exists at .venv — skipping creation."
fi

# Activate
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── 3. Upgrade pip ────────────────────────────────────────────────────────────
echo ""
echo "  [2/5] Upgrading pip ..."
pip install --quiet --upgrade pip

# ── 4. Install dependencies ───────────────────────────────────────────────────
echo ""
echo "  [3/5] Installing Python dependencies from requirements.txt ..."
pip install --quiet -r "$PROJECT_DIR/requirements.txt"

# ── 5. Verify WeasyPrint system deps (GTK / Pango) ───────────────────────────
echo ""
echo "  [4/5] Checking WeasyPrint system dependencies ..."
python -c "import weasyprint; print('  WeasyPrint OK')" 2>/dev/null || {
  echo ""
  echo "  WARNING: WeasyPrint requires system libraries (GTK, Pango, Cairo)."
  echo "  On macOS:  brew install pango gdk-pixbuf libffi cairo"
  echo "  On Ubuntu: sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libcairo2"
  echo "  WeasyPrint is optional — fpdf2 is the default PDF backend."
}

# ── 6. Download NotoSansSC font if missing ───────────────────────────────────
echo ""
echo "  [5/5] Checking NotoSansSC-Regular.otf font ..."
FONT_PATH="$PROJECT_DIR/NotoSansSC-Regular.otf"
if [ -f "$FONT_PATH" ] && [ "$(wc -c < "$FONT_PATH")" -gt 1000000 ]; then
  echo "  Font already present ($(wc -c < "$FONT_PATH" | tr -d ' ') bytes) — skipping download."
else
  echo "  Downloading NotoSansSC-Regular.otf from Google Fonts GitHub ..."
  FONT_URL="https://github.com/googlefonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$FONT_URL" -o "$FONT_PATH" && echo "  Font downloaded successfully."
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$FONT_URL" -O "$FONT_PATH" && echo "  Font downloaded successfully."
  else
    echo "  WARNING: curl/wget not found. Please download the font manually:"
    echo "    $FONT_URL"
    echo "  Place it as: $FONT_PATH"
  fi
fi

# ── 7. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "========================================================"
echo "  Setup complete!"
echo ""
echo "  Activate the environment:"
echo "    source .venv/bin/activate"
echo ""
echo "  Run the Streamlit web UI:"
echo "    streamlit run app.py"
echo ""
echo "  Run the FastAPI backend:"
echo "    uvicorn app.main:app --reload --port 8000"
echo "    Then open: http://localhost:8000/docs"
echo ""
echo "  Run CLI audit:"
echo "    python dpp_engine.py --csv data/test_data.csv"
echo "========================================================"
