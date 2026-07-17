"""Optional build-time QR for the /evidence footer — no external service.

Uses `segno` (preferred; pure-Python, pip install segno) or `qrcode` if present.
If neither is installed it prints a note and does nothing: the footer falls back
to showing the URL as plain text. Pass the demo laptop's LAN address (not
localhost) so a judge's phone can actually reach it:

    python -m demo.evidence.make_qr http://192.168.1.20:8000/evidence?full=1
"""
from __future__ import annotations

import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "qr.svg"
DEFAULT_URL = "http://localhost:8000/evidence?full=1"


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    try:
        import segno
        segno.make(url, error="m").save(str(OUT), scale=6, border=2, dark="#000000", light="#ffffff")
        print(f"wrote {OUT} for {url}")
        return 0
    except ImportError:
        pass
    try:
        import qrcode
        png = OUT.with_suffix(".png")
        qrcode.make(url).save(str(png))
        print(f"wrote {png} (PNG) for {url} — point evidence.html <img> at qr.png")
        return 0
    except ImportError:
        pass
    print("No QR library found (segno/qrcode). Skipping — the /evidence footer will "
          "show the URL as text. Run `pip install segno` then re-run to generate qr.svg.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
