#!/bin/bash
# ============================================================
#  Companion demo launcher  —  macOS
#
#  OFFLINE demo mode: no API key, no internet, deterministic.
#  For live mode (real STT / model / TTS voice), start this,
#  then open  http://127.0.0.1:8000/admin  and paste a key.
#
#  First run does a one-time setup (Python env + dependencies +
#  the evidence run). Later runs start instantly.
# ============================================================

# Double-clicking a .command opens Terminal in your home folder,
# so move to THIS launcher's folder, then into the app.
cd "$(dirname "$0")/triage-evidence-pack" || {
  echo "Could not find the 'triage-evidence-pack' folder next to this launcher."
  echo "Keep Start-Companion-Demo.command in the same folder as triage-evidence-pack."
  read -n 1 -s -r -p "Press any key to close..."; exit 1
}

# Offline, deterministic demo settings (same as the Windows launcher).
export DEMO_MODE=mock
export DEMO_TIMELINE=hf_decompensation
export DEMO_WORLD_SEED=1234

# --- 1. Python present? -------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "============================================================"
  echo "  Python 3 is not installed on this Mac."
  echo "  Install it once (default options are fine) from:"
  echo "      https://www.python.org/downloads/"
  echo "  then double-click this launcher again."
  echo "============================================================"
  open "https://www.python.org/downloads/" 2>/dev/null
  read -n 1 -s -r -p "Press any key to close..."; exit 1
fi

# --- 2. Local environment + dependencies (one time) ---------
if [ ! -d ".venv" ]; then
  echo "First run: creating a local Python environment (one time)..."
  python3 -m venv .venv || {
    echo "Could not create the environment. Try reinstalling Python 3."
    read -n 1 -s -r -p "Press any key to close..."; exit 1
  }
fi
# Use the venv's python for everything below.
source .venv/bin/activate

if ! python -c "import uvicorn, fastapi" >/dev/null 2>&1; then
  echo "First run: installing dependencies (one time, ~1 minute)..."
  python -m pip install --upgrade pip >/dev/null 2>&1
  python -m pip install -r requirements.txt || {
    echo "Dependency install failed. In Terminal, from this folder, try:"
    echo "    source .venv/bin/activate && pip install -r requirements.txt"
    read -n 1 -s -r -p "Press any key to close..."; exit 1
  }
fi

# --- 3. Evidence run so /evidence works (one time) ----------
if ! ls -d results/*/ >/dev/null 2>&1; then
  echo "First run: generating the offline evidence run (for the /evidence page)..."
  python run_evidence_pack.py --dry-run || \
    echo "(Evidence run skipped — the /evidence page may be unavailable, but the rest of the demo works.)"
fi

# --- 4. Start the server + open the device face -------------
echo "============================================================"
echo "  Companion demo  -  starting server (offline mock mode)"
echo "============================================================"
echo
echo "   Device (face) : http://127.0.0.1:8000/face"
echo "   Care team     : http://127.0.0.1:8000/nurse"
echo "   Evidence      : http://127.0.0.1:8000/evidence"
echo "   Admin / key   : http://127.0.0.1:8000/admin   (paste OpenAI key, go live)"
echo "   (fallback orb): http://127.0.0.1:8000/"
echo
echo "   Leave THIS window open. Close it (or press Ctrl-C) to STOP the demo."
echo "   Press F11 / green full-screen button in the browser for full screen."
echo "   Open http://127.0.0.1:8000/nurse in a SECOND window for the care team."
echo

# Open the face once the server is up. Prefer Chrome; fall back to the default browser.
( sleep 4; open -a "Google Chrome" "http://127.0.0.1:8000/face" 2>/dev/null \
        || open "http://127.0.0.1:8000/face" ) &

# The server runs in THIS window. Closing the window stops the demo.
exec python -m uvicorn demo.server.main:app --port 8000
