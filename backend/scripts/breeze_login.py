"""
One-time-per-day helper for the ICICI Breeze live market-data provider.

Breeze session tokens expire daily and can only be obtained via an
interactive browser login - there is no safe way to automate this without
handling the user's broker OTP/credentials directly, so this script does
not attempt it. Instead it:

  1. Prints the Breeze login URL for your API key.
  2. You log in in a browser and get redirected to a URL containing
     `apisession=<token>`.
  3. Paste that token back here; it's written into backend/.env as
     BREEZE_SESSION_TOKEN (replacing any previous value).

Run with:
    python -m scripts.breeze_login
"""
from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _read_api_key() -> str:
    api_key = os.environ.get("BREEZE_API_KEY", "")
    if not api_key and ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith("BREEZE_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break
    if not api_key:
        raise SystemExit("BREEZE_API_KEY not set - add it to backend/.env first, then rerun this script.")
    return api_key


def _write_session_token(token: str) -> None:
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith("BREEZE_SESSION_TOKEN="):
            lines[i] = f"BREEZE_SESSION_TOKEN={token}"
            replaced = True
            break
    if not replaced:
        lines.append(f"BREEZE_SESSION_TOKEN={token}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


def main() -> None:
    api_key = _read_api_key()
    login_url = f"https://api.icicidirect.com/apiuser/login?api_key={urllib.parse.quote(api_key)}"
    print("1. Open this URL in a browser and log in with your ICICI Direct credentials:\n")
    print(f"   {login_url}\n")
    print("2. After login you'll be redirected to a URL containing '?apisession=<token>'.")
    pasted = input("3. Paste the redirected URL (or just the token) here: ").strip()

    match = re.search(r"apisession=([^&\s]+)", pasted)
    token = match.group(1) if match else pasted
    if not token:
        raise SystemExit("No token provided.")

    _write_session_token(token)
    print(f"\nWrote BREEZE_SESSION_TOKEN to {ENV_PATH}. Restart the backend for it to take effect.")


if __name__ == "__main__":
    main()
