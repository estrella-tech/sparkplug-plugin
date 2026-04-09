"""
Sparkplug auth manager.

Uses Playwright to open my.sparkplug.app (or connect to an already-running
Chrome instance) and extract the JWT token from localStorage, then stores it
in ~/.sparkplug/sparkplug.json.
"""

import json
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path


CONFIG_PATH = Path.home() / ".sparkplug" / "sparkplug.json"
SPARKPLUG_URL = "https://my.sparkplug.app"


def extract_token_via_playwright(headless: bool = False, cdp_url: str = None) -> dict:
    """
    Launch (or connect to) a browser, navigate to Sparkplug, and pull the JWT
    token + group ID from localStorage.

    Args:
        headless: Run browser without UI (requires user to be already logged in).
        cdp_url: Optional Chrome DevTools Protocol URL to connect to an
                 existing Chrome instance (e.g. "http://localhost:9222").
    Returns:
        dict with jwt_token, group_id, user_id
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # Try connecting to an existing Chrome first (e.g. user's own browser)
        browser = None
        page = None

        if cdp_url:
            try:
                browser = p.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else None
                if context and context.pages:
                    # Look for an already-open Sparkplug tab
                    for pg in context.pages:
                        if "sparkplug.app" in pg.url:
                            page = pg
                            break
            except Exception:
                browser = None

        if browser is None:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context()

        if page is None:
            page = context.new_page()
            page.goto(SPARKPLUG_URL)
            page.wait_for_load_state("networkidle", timeout=15000)

        # Check if user is logged in; wait up to 2 min if not
        token = page.evaluate("localStorage.getItem('sparkplug::jwtToken')")
        if not token:
            print("Not logged in to Sparkplug. Please log in in the browser window...")
            deadline = time.time() + 120
            while not token and time.time() < deadline:
                time.sleep(2)
                token = page.evaluate("localStorage.getItem('sparkplug::jwtToken')")
            if not token:
                raise RuntimeError("Timed out waiting for Sparkplug login.")

        group_id = page.evaluate("localStorage.getItem('sparkplug::accountId')")
        user_id = page.evaluate("localStorage.getItem('sparkplug::userId')")

        config = {
            "jwt_token": token,
            "group_id": group_id or "691270b4e489475b3f933902",
            "user_id": user_id,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }

        browser.close()
        return config


def save_token(config: dict):
    """Write token config to disk with restricted permissions."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    try:
        os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Windows may not support Unix-style permissions
    print(f"Token saved → {CONFIG_PATH}")
    print(f"  group_id : {config.get('group_id')}")
    print(f"  user_id  : {config.get('user_id')}")


def setup(headless: bool = False, cdp_url: str = None):
    """Full setup flow: extract token and save config."""
    print("Extracting Sparkplug token via browser…")
    config = extract_token_via_playwright(headless=headless, cdp_url=cdp_url)
    save_token(config)
    print("✓ Sparkplug authentication configured.")
    return config


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Set up Sparkplug authentication")
    parser.add_argument("--headless", action="store_true", help="Run browser headlessly")
    parser.add_argument("--cdp", default=None, help="Chrome DevTools Protocol URL")
    args = parser.parse_args()

    setup(headless=args.headless, cdp_url=args.cdp)
