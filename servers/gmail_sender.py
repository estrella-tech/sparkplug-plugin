"""
Gmail sender — supports both App Password (SMTP) and OAuth2 (Gmail API).

Usage:
    from gmail_sender import send_email
    send_email(
        to=["giovanni@atomicfungi.com"],
        subject="Test",
        html_body="<h1>Hello</h1>",
    )

Auth methods (tried in order):
1. OAuth2 token at ~/.sparkplug/gmail_token.json (Gmail API)
2. App password at ~/.sparkplug/gmail_app_password.txt (SMTP)
"""

import base64
import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

CONFIG_DIR = Path.home() / ".sparkplug"
OAUTH_TOKEN_PATH = CONFIG_DIR / "gmail_token.json"
OAUTH_CREDS_PATH = CONFIG_DIR / "gmail_credentials.json"
APP_PASSWORD_PATH = CONFIG_DIR / "gmail_app_password.txt"
SENDER_EMAIL = "giovanni@atomicfungi.com"


def send_email(to: list[str], subject: str, html_body: str, sender: str = SENDER_EMAIL) -> bool:
    """Send an HTML email. Returns True on success."""
    # Try OAuth2 first
    if OAUTH_TOKEN_PATH.exists() and OAUTH_CREDS_PATH.exists():
        try:
            return _send_via_oauth2(to, subject, html_body, sender)
        except Exception as e:
            print(f"  OAuth2 send failed: {e}")
            print("  Falling back to SMTP...")

    # Try App Password
    if APP_PASSWORD_PATH.exists():
        password = APP_PASSWORD_PATH.read_text().strip()
        return _send_via_smtp(to, subject, html_body, sender, password)

    print("  No email credentials found. Set up one of:")
    print(f"    OAuth2: Run 'python gmail_sender.py setup' then authorize in browser")
    print(f"    App Password: Save your Gmail app password to {APP_PASSWORD_PATH}")
    return False


def _send_via_smtp(to: list[str], subject: str, html_body: str, sender: str, password: str) -> bool:
    """Send via Gmail SMTP with App Password."""
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, to, msg.as_string())

    print(f"  Email sent via SMTP to {len(to)} recipients")
    return True


def _send_via_oauth2(to: list[str], subject: str, html_body: str, sender: str) -> bool:
    """Send via Gmail API with OAuth2."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]

    creds = None
    if OAUTH_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        OAUTH_TOKEN_PATH.write_text(creds.to_json())

    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()

    print(f"  Email sent via Gmail API to {len(to)} recipients")
    return True


def setup_oauth():
    """Interactive OAuth2 setup — run once, then automated forever."""
    print("Gmail OAuth2 Setup")
    print("=" * 40)

    if not OAUTH_CREDS_PATH.exists():
        print(f"\nYou need a Google Cloud OAuth2 credentials file.")
        print(f"1. Go to https://console.cloud.google.com/apis/credentials")
        print(f"2. Create a project (or use existing)")
        print(f"3. Enable the Gmail API")
        print(f"4. Create OAuth 2.0 Client ID (Desktop app)")
        print(f"5. Download the JSON and save it to:")
        print(f"   {OAUTH_CREDS_PATH}")
        print(f"\nThen run this script again.")
        return

    from google_auth_oauthlib.flow import InstalledAppFlow
    SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]

    print("Opening browser for authorization...")
    flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    OAUTH_TOKEN_PATH.write_text(creds.to_json())
    print(f"\nToken saved to {OAUTH_TOKEN_PATH}")
    print("Gmail OAuth2 is now configured. Emails will send automatically.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup_oauth()
    else:
        # Test send
        success = send_email(
            to=[SENDER_EMAIL],
            subject="AF Daily Intel — Test Email",
            html_body="<h1 style='color:#1a3c2e'>Test email from Sparkplug pipeline</h1><p>If you see this, email sending works.</p>",
        )
        if success:
            print("Test email sent successfully!")
