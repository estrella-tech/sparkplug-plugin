#!/usr/bin/env python3
"""
Set up Gmail OAuth for Jared's account (jared@atomicfungi.com).
Opens a browser for Jared to log in and authorize. Saves token separately.

Usage: python scripts/setup_jared_gmail.py
"""

from pathlib import Path

CONFIG_DIR = Path.home() / ".sparkplug"
JARED_TOKEN_PATH = CONFIG_DIR / "gmail_token_jared.json"
GMAIL_CREDS_PATH = CONFIG_DIR / "gmail_credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]


def main():
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not GMAIL_CREDS_PATH.exists():
        print(f"ERROR: Gmail credentials not found at {GMAIL_CREDS_PATH}")
        print("Copy your Google Cloud OAuth client JSON there first.")
        return

    print("=" * 50)
    print("Gmail OAuth Setup for Jared")
    print("=" * 50)
    print()
    print("A browser window will open.")
    print("Jared needs to log in with jared@atomicfungi.com")
    print("and grant all permissions.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(GMAIL_CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    JARED_TOKEN_PATH.write_text(creds.to_json())

    print()
    print(f"Token saved to {JARED_TOKEN_PATH}")
    print("Jared's Gmail is now connected.")


if __name__ == "__main__":
    main()
