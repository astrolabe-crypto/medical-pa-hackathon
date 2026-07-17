# Running the Companion demo on a Mac

The Windows `.bat` file does **not** run on macOS. Use `Start-Companion-Demo.command`
instead — it does the same thing, plus a one-time setup on first run.

## 0. Get the code onto the Mac

Repo (private): **https://github.com/astrolabe-crypto/medical-pa-hackathon**

Either:
- **Download ZIP** — on the GitHub page: green **Code** button → **Download ZIP** →
  double-click to unzip. (Simplest; works even for a private repo while you're logged in.)
- **or Clone** — in Terminal: `git clone https://github.com/astrolabe-crypto/medical-pa-hackathon.git`

## 1. Install Python 3 (one time, ~2 min)

Download from **https://www.python.org/downloads/** and run the installer with the
default options. That's the only manual install you need.

## 2. Start the demo

**Double-click `Start-Companion-Demo.command`.**

- **First launch only** takes ~1–2 minutes: it builds a local Python environment,
  installs the dependencies, and generates the offline evidence run. Leave it be.
- Later launches start in a few seconds.
- A Terminal window opens and **stays open** — that's the server. **Leave it running;
  close it (or press Ctrl-C) to stop the demo.**
- Chrome (or your default browser) opens the **device face** at `http://127.0.0.1:8000/face`.
  Use the browser's full-screen button.
- Open a **second window** at `http://127.0.0.1:8000/nurse` for the care-team view.

### If macOS blocks the launcher

Downloaded files are sometimes quarantined. If double-click does nothing or you see
"unidentified developer":

- **Right-click** `Start-Companion-Demo.command` → **Open** → **Open** (only needed once), **or**
- In Terminal, from this folder:
  ```
  chmod +x Start-Companion-Demo.command
  xattr -d com.apple.quarantine Start-Companion-Demo.command 2>/dev/null
  ```

## 3. Everything else is the same as the runbook

Key map, the 3-minute sequence, and fallbacks are in **`DEMO-RUNBOOK.md`**.
The only differences on Mac: you launch with the `.command` (not the `.bat`), and
full-screen is the browser's green button / `Ctrl-Cmd-F`, not `F11`.

## 4. Going live with an OpenAI key (optional)

No terminal needed. With the demo running, open **`http://127.0.0.1:8000/admin`**,
paste your OpenAI key → **Test connection** → **Save & Go Live**. One click back to
**Mock (safe)** any time. The key lives in memory only — never written to disk or git.
