#!/bin/bash
# ============================================================
#  Companion demo launcher  —  macOS
#
#  OFFLINE demo mode: no API key, no internet, deterministic.
#  For live mode (real STT / model / TTS voice), start this,
#  then open http://127.0.0.1:8000/admin and switch to live using configured keys.
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

# Start live automatically when the configured provider keys are present. This
# makes the usual double-click workflow genuinely one-click; set
# DEMO_START_MODE=mock before running the script if an offline rehearsal is
# wanted instead. We only check that values exist — keys are never read or
# printed by this launcher.
if [ "${DEMO_START_MODE:-}" = "mock" ]; then
  export DEMO_MODE=mock
elif [ -f ".env" ] \
  && grep -qE '^ANTHROPIC_API_KEY=.+$' .env \
  && grep -qE '^ELEVENLABS_API_KEY=.+$' .env; then
  export DEMO_MODE=live
else
  export DEMO_MODE=mock
fi
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
  if ! python -m pip install -r requirements.txt; then
    echo "Full install hit a snag; installing the core packages needed to run..."
    python -m pip install "fastapi>=0.110" "uvicorn>=0.27" "python-multipart>=0.0.9" \
                          "pyyaml>=6.0" "httpx>=0.27" || {
      echo "Dependency install failed. In Terminal, from this folder, try:"
      echo "    source .venv/bin/activate && pip install -r requirements.txt"
      read -n 1 -s -r -p "Press any key to close..."; exit 1
    }
  fi
fi

# --- 3. Evidence run so /evidence works (one time) ----------
if ! ls -d results/*/ >/dev/null 2>&1; then
  echo "First run: generating the offline evidence run (for the /evidence page)..."
  python run_evidence_pack.py --dry-run || \
    echo "(Evidence run skipped — the /evidence page may be unavailable, but the rest of the demo works.)"
fi

# --- 4. Clear a prior Companion server before starting fresh ---------------
# A long-lived browser event stream can keep an old Uvicorn worker alive after
# its Terminal is closed. It no longer listens on port 8000, but Chrome can
# remain attached to it. Match only this project's Uvicorn command, ask it to
# stop cleanly, then release any worker still holding an old connection.
companion_pids() {
  pgrep -f 'uvicorn demo\.server\.main:app --port 8000' 2>/dev/null || true
}

existing_companion_pids="$(companion_pids)"
if [ -n "$existing_companion_pids" ]; then
  echo "Stopping previous Companion Demo server…"
  for companion_pid in $existing_companion_pids; do
    case "$companion_pid" in
      *[!0-9]*|'') ;;
      *) kill -INT "$companion_pid" 2>/dev/null || true ;;
    esac
  done
  for shutdown_attempt in {1..5}; do
    remaining_companion_pids="$(companion_pids)"
    [ -z "$remaining_companion_pids" ] && break
    sleep 1
  done
  # Only an already-detached Companion worker reaches here; this avoids stale
  # SSE connections being inherited by a newly opened Chrome demo window.
  for companion_pid in ${remaining_companion_pids:-}; do
    case "$companion_pid" in
      *[!0-9]*|'') ;;
      *) kill -KILL "$companion_pid" 2>/dev/null || true ;;
    esac
  done
fi

# --- 5. Start the server + arrange the three-screen demo ----
echo "============================================================"
echo "  Companion demo  -  starting server (${DEMO_MODE} mode)"
echo "============================================================"
echo
echo "   Device (face) : http://127.0.0.1:8000/face"
echo "   Care team     : http://127.0.0.1:8000/nurse"
echo "   Evidence      : http://127.0.0.1:8000/evidence"
echo "   Admin         : http://127.0.0.1:8000/admin   (switch configured Anthropic/ElevenLabs demo live)"
echo "   (fallback orb): http://127.0.0.1:8000/"
echo
echo "   Leave THIS window open. Close it (or press Ctrl-C) to STOP the demo."
echo "   Chrome will open three windows automatically: face left, care team"
echo "   top-right, evidence bottom-right. Existing Chrome windows are untouched."
echo

# Wait for the HTTP server, then open three separate Chrome windows and tile
# them against the current desktop. Finder reports display bounds in macOS
# points, so this works on Retina and non-Retina displays without hard-coding
# the panel resolution. The script never closes or rearranges unrelated tabs.
open_demo_layout() {
  local face_url="http://127.0.0.1:8000/face"
  local nurse_url="http://127.0.0.1:8000/nurse"
  local evidence_url="http://127.0.0.1:8000/evidence"
  local attempt

  for attempt in {1..30}; do
    if curl -fsS "http://127.0.0.1:8000/api/config" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  if ! curl -fsS "http://127.0.0.1:8000/api/config" >/dev/null 2>&1; then
    echo "Browser windows were not opened because the server did not become ready."
    return
  fi

  if /usr/bin/osascript - "$face_url" "$nurse_url" "$evidence_url" <<'APPLESCRIPT'
on run argv
  set faceURL to item 1 of argv
  set nurseURL to item 2 of argv
  set evidenceURL to item 3 of argv

  tell application "Finder" to set {leftEdge, topEdge, rightEdge, bottomEdge} to bounds of window of desktop
  set screenWidth to rightEdge - leftEdge
  set screenHeight to bottomEdge - topEdge
  set gap to 6
  set titleBar to 26
  set splitX to (leftEdge + (screenWidth * 0.56)) as integer
  set splitY to (topEdge + (screenHeight * 0.5)) as integer

  tell application "Google Chrome"
    activate
    set faceWindow to make new window
    set URL of active tab of faceWindow to faceURL
    set bounds of faceWindow to {leftEdge + gap, topEdge + titleBar, splitX - gap, bottomEdge - gap}

    set nurseWindow to make new window
    set URL of active tab of nurseWindow to nurseURL
    set bounds of nurseWindow to {splitX + gap, topEdge + titleBar, rightEdge - gap, splitY - gap}

    set evidenceWindow to make new window
    set URL of active tab of evidenceWindow to evidenceURL
    set bounds of evidenceWindow to {splitX + gap, splitY + gap, rightEdge - gap, bottomEdge - gap}

    set index of faceWindow to 1
  end tell
end run
APPLESCRIPT
  then
    echo "Opened and arranged the face, care-team, and evidence windows."
  else
    echo "Chrome layout automation was unavailable; opening the three pages normally."
    open -a "Google Chrome" "$face_url" "$nurse_url" "$evidence_url" 2>/dev/null \
      || open "$face_url" "$nurse_url" "$evidence_url"
  fi
}

open_demo_layout &

# The server runs in THIS window. Closing the window stops the demo.
exec python -m uvicorn demo.server.main:app --port 8000
