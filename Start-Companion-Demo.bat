@echo off
title Companion demo launcher
cd /d "%~dp0triage-evidence-pack"

REM ============================================================
REM  OFFLINE demo mode: no API key, no internet, deterministic.
REM  For the live pipeline instead, see DEMO-RUNBOOK.md ("Live mode").
REM ============================================================
set DEMO_MODE=mock
set DEMO_TIMELINE=hf_decompensation
set DEMO_WORLD_SEED=1234

echo ============================================================
echo   Companion demo  -  starting server (offline mock mode)
echo ============================================================
echo.
echo   Device (face) : http://127.0.0.1:8000/face
echo   Care team     : http://127.0.0.1:8000/nurse
echo   Evidence      : http://127.0.0.1:8000/evidence
echo   Admin / key   : http://127.0.0.1:8000/admin   (paste OpenAI key, go live)
echo   (fallback orb): http://127.0.0.1:8000/
echo.

REM Server runs in its own window. Close THAT window to stop the demo.
start "Companion demo server" cmd /k "python -m uvicorn demo.server.main:app --port 8000"

echo Waiting for the server to come up...
timeout /t 4 /nobreak >nul

REM Open the device face (your main screen). Open /nurse in a 2nd window at the beat.
start "" http://127.0.0.1:8000/face

echo.
echo   The face opened in your browser. Press F11 for full screen.
echo   Open http://127.0.0.1:8000/nurse in a SECOND window for the care-team view.
echo.
echo   This launcher window can be closed now.
echo   The SERVER is the OTHER window - close it to stop the demo.
echo.
pause
