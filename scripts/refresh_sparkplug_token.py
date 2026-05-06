#!/usr/bin/env python3
"""
Sparkplug JWT token refresh agent.

Strategy (tried in order):
1. Read from the desktop app's Electron local storage (Windows AppData)
2. Browser automation via Playwright (headless login)

Usage:
    python refresh_sparkplug_token.py           # refresh token
    python refresh_sparkplug_token.py --setup   # save credentials for automation
"""

import json
import os
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".sparkplug"
SPARKPLUG_CONFIG = CONFIG_DIR / "sparkplug.json"
CREDENTIALS_PATH = CONFIG_DIR / "sparkplug_credentials.json"
SPARKPLUG_URL = "https://my.sparkplug.app"

# Common Electron app data locations for Sparkplug on Windows
ELECTRON_PATHS = [
    Path.home() / "AppData" / "Roaming" / "Sparkplug" / "Local Storage" / "leveldb",
    Path.home() / "AppData" / "Roaming" / "sparkplug" / "Local Storage" / "leveldb",
    Path.home() / "AppData" / "Local" / "Sparkplug" / "Local Storage" / "leveldb",
    Path.home() / "AppData" / "Local" / "sparkplug" / "Local Storage" / "leveldb",
    # macOS
    Path.home() / "Library" / "Application Support" / "Sparkplug" / "Local Storage" / "leveldb",
]

# Keys Sparkplug might use in localStorage
TOKEN_KEYS = ["token", "jwt_token", "authToken", "auth_token", "accessToken", "access_token", "id_token"]


def load_existing_config() -> dict:
    if SPARKPLUG_CONFIG.exists():
        with open(SPARKPLUG_CONFIG) as f:
            return json.load(f)
    return {}


def save_token(token: str):
    config = load_existing_config()
    config["jwt_token"] = token
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SPARKPLUG_CONFIG, "w") as f:
        json.dump(config, f, indent=2)
    try:
        import stat
        os.chmod(SPARKPLUG_CONFIG, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    print(f"  Token saved to {SPARKPLUG_CONFIG}")


def try_electron_leveldb() -> str | None:
    """Try to extract JWT from Electron app's LevelDB storage."""
    try:
        import plyvel  # pip install plyvel (Linux/Mac) or plyvel-win32 (Windows)
    except ImportError:
        return None

    for db_path in ELECTRON_PATHS:
        if not db_path.exists():
            continue
        print(f"  Found Electron storage at {db_path}")
        try:
            db = plyvel.DB(str(db_path))
            for key, value in db:
                key_str = key.decode("utf-8", errors="ignore")
                val_str = value.decode("utf-8", errors="ignore")
                for token_key in TOKEN_KEYS:
                    if token_key in key_str.lower():
                        # LevelDB values are prefixed with a type byte
                        clean = val_str.lstrip("\x00\x01").strip().strip('"')
                        if clean and len(clean) > 20:
                            db.close()
                            print(f"  Found token via Electron storage (key: {key_str})")
                            return clean
            db.close()
        except Exception as e:
            print(f"  LevelDB read failed: {e}")
    return None


def try_electron_json_files() -> str | None:
    """Check AppData for any JSON config files the desktop app might write."""
    search_roots = [
        Path.home() / "AppData" / "Roaming",
        Path.home() / "AppData" / "Local",
        Path.home() / "Library" / "Application Support",
    ]
    for root in search_roots:
        if not root.exists():
            continue
        for candidate in root.glob("*sparkplug*/**/*.json"):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8", errors="ignore"))
                for key in TOKEN_KEYS:
                    token = data.get(key, "")
                    if token and len(str(token)) > 40 and "." in str(token):
                        print(f"  Found token in {candidate} (key: {key})")
                        return str(token)
            except Exception:
                pass
    return None


def try_playwright(headless: bool = True) -> str | None:
    """Log in via Playwright and extract JWT from localStorage."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright not installed. Run: pip install playwright && playwright install chromium")
        return None

    if not CREDENTIALS_PATH.exists():
        print(f"  No credentials found at {CREDENTIALS_PATH}")
        print("  Run with --setup to save credentials for automation.")
        return None

    creds = json.loads(CREDENTIALS_PATH.read_text())
    email = creds.get("email", "")
    password = creds.get("password", "")
    if not email or not password:
        print("  Credentials file missing email or password.")
        return None

    print(f"  Launching browser to log in as {email}...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()

            page.goto(SPARKPLUG_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)

            # Try to detect if already logged in
            token = _extract_token_from_storage(page)
            if token:
                browser.close()
                return token

            # Fill login form — try common selectors
            _fill_login_form(page, email, password)

            # Wait for redirect after login
            page.wait_for_load_state("networkidle", timeout=20000)

            # Give the app a moment to write localStorage
            page.wait_for_timeout(2000)

            token = _extract_token_from_storage(page)
            browser.close()

            if token:
                print("  Login successful, token extracted.")
            else:
                print("  Login may have succeeded but couldn't find token in localStorage.")
                print(f"  Try running with HEADLESS=0: HEADLESS=0 python {__file__}")
            return token
    except Exception as e:
        print(f"  Playwright error: {e}")
        return None


def _extract_token_from_storage(page) -> str | None:
    """Check localStorage for any JWT-shaped value."""
    for key in TOKEN_KEYS:
        try:
            val = page.evaluate(f"localStorage.getItem('{key}')")
            if val and len(str(val)) > 40:
                clean = str(val).strip().strip('"')
                if "." in clean:  # JWTs have dots
                    return clean
        except Exception:
            pass
    # Broader scan: grab all localStorage keys and look for anything JWT-shaped
    try:
        all_storage = page.evaluate("""
            (() => {
                const out = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    out[k] = localStorage.getItem(k);
                }
                return out;
            })()
        """)
        for k, v in (all_storage or {}).items():
            if v and isinstance(v, str) and len(v) > 40 and v.count(".") >= 2:
                # Looks like a JWT (three base64 segments)
                return v.strip().strip('"')
    except Exception:
        pass
    return None


def _fill_login_form(page, email: str, password: str):
    """Try common login form selectors."""
    selectors_email = ['input[type="email"]', 'input[name="email"]', 'input[name="username"]', '#email', '#username']
    selectors_pass = ['input[type="password"]', 'input[name="password"]', '#password']
    selectors_submit = ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("Log in")', 'button:has-text("Sign in")', 'button:has-text("Login")']

    for sel in selectors_email:
        try:
            page.fill(sel, email, timeout=3000)
            break
        except Exception:
            pass

    for sel in selectors_pass:
        try:
            page.fill(sel, password, timeout=3000)
            break
        except Exception:
            pass

    for sel in selectors_submit:
        try:
            page.click(sel, timeout=3000)
            break
        except Exception:
            pass


def setup_credentials():
    """Interactive setup to save login credentials."""
    print("Sparkplug Token Auto-Refresh Setup")
    print("=" * 40)
    print("Credentials are stored locally at:")
    print(f"  {CREDENTIALS_PATH}")
    print()

    email = input("Sparkplug email: ").strip()
    import getpass
    password = getpass.getpass("Sparkplug password: ")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps({"email": email, "password": password}, indent=2))
    try:
        import stat
        os.chmod(CREDENTIALS_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass

    print(f"\nCredentials saved to {CREDENTIALS_PATH}")
    print("Testing login now...")
    token = try_playwright(headless=False)  # show browser on first setup
    if token:
        save_token(token)
        print("\nSetup complete. Token refresh will run automatically.")
    else:
        print("\nCouldn't extract token automatically.")
        print("The login page selectors may need adjustment for Sparkplug's UI.")


def refresh_token() -> bool:
    """Main refresh flow. Returns True if token was updated."""
    print("[Token Refresh] Attempting to refresh Sparkplug JWT...")

    # Strategy 1: Desktop app JSON files (fast, no login needed)
    print("  [1/3] Checking desktop app config files...")
    token = try_electron_json_files()
    if token:
        save_token(token)
        return True

    # Strategy 2: Electron LevelDB (requires plyvel)
    print("  [2/3] Checking Electron LevelDB storage...")
    token = try_electron_leveldb()
    if token:
        save_token(token)
        return True

    # Strategy 3: Playwright browser automation
    headless = os.environ.get("HEADLESS", "1") != "0"
    print(f"  [3/3] Browser automation (headless={headless})...")
    token = try_playwright(headless=headless)
    if token:
        save_token(token)
        return True

    print("\n[Token Refresh] All strategies failed.")
    print("Manual fix: DevTools → Application → Local Storage → my.sparkplug.app → copy token value")
    print(f"Then update jwt_token in: {SPARKPLUG_CONFIG}")
    return False


if __name__ == "__main__":
    if "--setup" in sys.argv:
        setup_credentials()
    else:
        success = refresh_token()
        sys.exit(0 if success else 1)
