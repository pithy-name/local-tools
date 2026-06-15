#!/usr/bin/env bash
# setup.sh — one-shot setup for redact.py
# Run once from the redaction-tool/ directory: bash setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo "  redact.py — local setup"
echo "═══════════════════════════════════════════════════"

# ── 1. Pick a Python interpreter ──────────────────────────────────────────────
# This tool is TESTED ON PYTHON 3.11 only (see the README). The system python3
# on macOS is 3.9, which CANNOT install the spaCy stack (thinc >=8.3.12 needs
# Python >=3.10), so we never use it. We prefer 3.11; a newer 3.x is accepted as
# a fallback so a machine without 3.11 can still install.
PY=""
for cand in python3.11 python3.12 python3.13; do
    if command -v "$cand" &>/dev/null; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "ERROR: need Python 3.11+ (this tool is tested on 3.11); none found."
    echo "Install it with: brew install python@3.11"
    exit 1
fi
PYVER=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
# Defensive floor check — guards against the probe list being widened later.
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
    echo "ERROR: ${PY} is Python ${PYVER}; need >=3.11."
    exit 1
fi
echo "✓ Using ${PY} (Python ${PYVER})"

# ── 2. Create virtualenv ──────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "→ Creating virtual environment (.venv)…"
    "$PY" -m venv .venv
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
# Reads the model name from config.yaml if present, falls back to en_core_web_sm
SPACY_MODEL="en_core_web_sm"
if command -v python3 &>/dev/null && [ -f config.yaml ]; then
    SPACY_MODEL=$(python3 -c "
import yaml, sys
try:
    cfg = yaml.safe_load(open('config.yaml'))
    print(cfg.get('spacy_model', 'en_core_web_sm'))
except:
    print('en_core_web_sm')
")
fi

echo "→ Downloading spaCy model '${SPACY_MODEL}'…"
echo "  (en_core_web_sm ≈ 12 MB; en_core_web_lg ≈ 750 MB — first run downloads it)"
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
echo "    python redact.py /path/to/your/folder --dry-run"
echo ""
echo "  Full redaction (output goes to <folder>/redacted/):"
echo "    python redact.py /path/to/your/folder"
echo "═══════════════════════════════════════════════════"
