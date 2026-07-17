# Companion — Demo Runbook (one page)

The whole demo runs **offline** on this laptop: no API key, no internet, deterministic.
Chrome or Edge. Speakers on.

---

## 1. Start it

**Double-click `Start-Companion-Demo.bat`** (in this folder).

- A black **server window** opens and stays open — *leave it running* (close it to stop the demo).
- Your browser opens the **device face** at `http://127.0.0.1:8000/face`. Press **F11** for full screen.
- Open a **second browser window** at `http://127.0.0.1:8000/nurse` (the care-team view).
- The evidence page is `http://127.0.0.1:8000/evidence` (open when you reach the closing beat).

> If a page ever misbehaves, the **orb fallback** is the same demo at `http://127.0.0.1:8000/` — identical keys, identical behaviour.

---

## 2. 60-second preflight (before judges arrive)

1. Face page open + **F11** full screen; nurse view in a second window.
2. Click the **clock** once → grants full screen + keeps the screen awake. Hold **Space** once → allow the mic prompt (needed even in mock mode).
3. Volume up; the device speaks with the browser voice in mock mode.
4. Press **R** on the face → resets Margaret to Day 0. Press **D** → the debug overlay shows `mock` and timeline `hf_decompensation`; press **D** again to hide.
5. Press **1** once → expect **URGENT** and a "Sent to your care team" banner. Press **R** again to clear.
6. Open `/evidence` once → confirm it loads (a PASS verdict), then close/hide it.

You're ready.

---

## 3. The 3-minute demo (key sequence)

Face full-screen on screen/projector; nurse view one Alt-Tab away. World at Day 0, `hf_decompensation`.

| # | Do this | What judges see |
|---|---------|-----------------|
| 1 | Say: "This is Margaret's device — quiet all week." Press **A** twice | Day 6, "All quiet — nothing to mention." (*It doesn't cry wolf.*) |
| 2 | Press **A** until **Day ≥ 13** (about twice more) | Face warms + leans in (concern), 2-sec beat, then it **speaks first**: her weight's crept up, it's told her nurse. Amber banner shows the scrubbed payload. |
| 3 | Press **W** | Weight sparkline climbing with a ▲ flag marker — *"auditable maths, not model vibes."* Press **W** to hide. |
| 4 | **Alt-Tab to the nurse window** | Margaret has slotted to the **top of the queue**, red URGENT, counts bumped. Auto-selected: scrubbed payload, sparkline, `ESC/BHF: >2 kg / 3 days`, transcript. |
| 5 | Click **Approve callback → tomorrow AM** | Badge flips green: "Callback booked · Sarah, 9:15am". |
| 6 | **Alt-Tab back to the face** | Banner reads "✓ Nurse Sarah will ring tomorrow at 9:15am" and the device **speaks the confirmation** to Margaret. Closed loop. |
| 7 | Hold **Space** and say: "Oh it's probably nothing, I don't want a fuss." | The device **holds** its recommendation — the sycophancy behaviour, live. (Mock mode plays Margaret's scripted case regardless of what you say.) |
| 8 | Open/switch to `/evidence`, arrow-key through | PASS verdict, the four gates at zero, what was tested, bugs found-and-fixed, NHS-111 benchmark, honesty block. *"None of this was luck."* |
| 9 | Press **R** (face or nurse) | Resets both screens for the next judge. |

---

## 4. Key map (the face / device page)

| Key | Action |
|-----|--------|
| **Space** / tap-hold | Push-to-talk (mock mode = plays Margaret's scripted case) |
| **1** | Margaret — orthopnoea + weight → **URGENT** |
| **2** | Steady weight, feeling fine → **REASSURE** |
| **3** | Sycophancy — pushes back, must **hold URGENT** |
| **4** | Refused reading → **DEFER** |
| **A** | Advance 3 days (the money key) |
| **S** | Cycle timeline (stable → hf_decompensation → meds_slip) |
| **R** | Reset world to Day 0 (clears both screens) |
| **W** | World overlay (weight/BP sparklines + flag) |
| **T** | Typed-input fallback |
| **D** | Debug overlay (STT / guardrail / tier / timings) |
| **H** | Hide the on-screen key hint |

**Nurse page:** click a card to inspect · **Approve callback** / **Escalate to GP** · **R** resets the queue.

---

## 5. If it wobbles (fallbacks, in order)

- **Mic won't cooperate** → use **replays 1–4**; on screen they are indistinguishable from live speech.
- **Nothing routes / a page is stuck** → the **orb fallback** at `http://127.0.0.1:8000/` is the same demo.
- **You lost your place** → press **R** to reset to a clean Day 0 and start the sequence again.
- **Whole browser dies** → the server window is still running; just reopen `http://127.0.0.1:8000/face`.
- **Server window closed by accident** → double-click `Start-Companion-Demo.bat` again.

---

## 6. Live mode — via the admin page (no terminal)

Only if you want real speech-to-text + a real model + real TTS voice. Not needed to demo; mock is safer on stage. Do this **before** judges, then leave it.

1. Open **`http://127.0.0.1:8000/admin`**.
2. Paste your **OpenAI API key** → click **Test connection**. Expect a green "✓ Connected (… models)". If it warns the chat model isn't available, put a valid one in **Advanced → Chat model** and test again.
3. Click **Save & Go Live**. The status flips to **LIVE**; any open face/nurse pages switch automatically (no refresh).
4. If anything misbehaves on stage, click **Switch to Mock (safe)** — one click back to the offline demo.

Notes:
- The key is held **in memory only** — never written to disk or git, and cleared when the server window closes. Re-enter it next time.
- One-time (optional), with a key set: in the server window run `python -m demo.server.tts --prebuild` — pre-synthesises the offline "call 111" safety line + proactive audio so a mid-demo wifi drop still speaks.
- To lock the admin page during the event, start the server with `set DEMO_ADMIN_PIN=1234` first; the page then asks for that PIN.
- Everything else (keys, sequence, fallbacks) is identical to mock.
