#!/usr/bin/env bash
# setup.sh — one-shot setup for redact.py
# Run once from the redaction-tool/ directory: bash setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo "  redact.py — local setup"
echo "═══════════════════════════════════════════════════"

# ── 1. Python version check ───────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    echo "Install Python via: brew install python"
    exit 1
fi
PYVER=$(python3 -c "import sys; print('%d.%d' % sys.version_info[:2])")
PYMAJ=$(python3 -c "import sys; print(sys.version_info[0])")
PYMIN=$(python3 -c "import sys; print(sys.version_info[1])")
echo "✓ Python ${PYVER} found"

if [ "$PYMAJ" -lt 3 ] || { [ "$PYMAJ" -eq 3 ] && [ "$PYMIN" -lt 9 ]; }; then
    echo "ERROR: Python 3.9+ required (found ${PYVER})"
    exit 1
fi

# ── 2. Create virtualenv ──────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "→ Creating virtual environment (.venv)…"
    python3 -m venv .venv
    echo "✓ Virtualenv created"
else
    echo "✓ Virtualenv already exists"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo "✓ Virtualenv activated"

# ── 3. Install packages ───────────────────────────────────────────────────────
echo "→ Installing Python packages (this may take a few minutes)…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "✓ Packages installed"

# ── 4. Download spaCy NLP model ───────────────────────────────────────────────
# Reads the model name from config.yaml if present, falls back to en_core_web_lg
SPACY_MODEL="en_core_web_lg"
if command -v python3 &>/dev/null && [ -f config.yaml ]; then
    SPACY_MODEL=$(python3 -c "
import yaml, sys
try:
    cfg = yaml.safe_load(open('config.yaml'))
    print(cfg.get('spacy_model', 'en_core_web_lg'))
except:
    print('en_core_web_lg')
")
fi

echo "→ Downloading spaCy model '${SPACY_MODEL}'…"
echo "  (en_core_web_lg is ~750 MB — grab a coffee if this is your first run)"
python3 -m spacy download "${SPACY_MODEL}"
echo "✓ spaCy model '${SPACY_MODEL}' ready"

# ── 5. Verify Apple Vision availability ──────────────────────────────────────
echo "→ Checking Apple Vision OCR…"
python3 -c "
import sys
try:
    import objc, Vision
    print('✓ Apple Vision OCR available (on-device M-series)')
except ImportError as e:
    print(f'  Apple Vision not available ({e})')
    print('  Tesseract fallback will be used if installed')
"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit config.yaml to add custom keywords"
echo "  2. Activate the venv:  source .venv/bin/activate"
echo ""
echo "  Dry run (no files written — just shows what would be redacted):"
echo "    python redact.py /path/to/your/notion-export --dry-run"
echo ""
echo "  Full redaction (output goes to notion-export/redacted/):"
echo "    python redact.py /path/to/your/notion-export"
echo "═══════════════════════════════════════════════════"
