"""
Shared utilities for email generation scripts.
Gmail API, Gemini API, enrichment data loading, company matching.
"""

import csv
import json
import os
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

CONFIG_DIR = Path.home() / ".sparkplug"
PROJECT_ROOT = Path(__file__).parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports"
CONFIG_PATH = PROJECT_ROOT / "config"

GMAIL_TOKEN_PATH = CONFIG_DIR / "gmail_token.json"
GMAIL_CREDS_PATH = CONFIG_DIR / "gmail_credentials.json"
GEMINI_KEY_PATH = CONFIG_DIR / "gemini_key.txt"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/calendar",
]


def get_gmail_service():
    """Build authenticated Gmail API service."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if GMAIL_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(GMAIL_CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        GMAIL_TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def generate_with_llm(prompt: str, system: str = None, max_tokens: int = 2048) -> str:
    """Call Anthropic Claude API (Sonnet). ~$0.01 per email rewrite."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    anthropic_key_path = CONFIG_DIR / "anthropic_key.txt"
    if not api_key and anthropic_key_path.exists():
        api_key = anthropic_key_path.read_text().strip()
    if not api_key:
        raise RuntimeError(f"No Anthropic API key. Set ANTHROPIC_API_KEY or save to {anthropic_key_path}")

    client = anthropic.Anthropic(api_key=api_key)
    kwargs = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return response.content[0].text.strip()


def load_enrichment_data() -> dict:
    """Load and index all enrichment sources for company matching."""

    def _load_json(name):
        path = EXPORTS_DIR / f"{name}.json"
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    # HubSpot companies indexed by normalized name and domain
    companies_raw = _load_json("hubspot_companies").get("data", [])
    companies_by_name = {}
    companies_by_domain = {}
    for c in companies_raw:
        name = c.get("name", "")
        if name:
            companies_by_name[name.lower().strip()] = c
        domain = c.get("domain", "")
        if domain:
            companies_by_domain[domain.lower().strip()] = c

    # HubSpot deals indexed by company name (from deal name)
    deals_raw = _load_json("hubspot_deals").get("data", [])
    deals_by_company = {}
    for d in deals_raw:
        # Deal names often look like "Company Name — Deal Type"
        dname = d.get("name", "")
        # Split on em-dash or en-dash only, not hyphens (company names can have hyphens)
        company_part = dname.split("—")[0].split("–")[0].strip()
        if company_part:
            deals_by_company.setdefault(company_part.lower(), []).append(d)

    # Snap engagement: budtender names indexed by retailer
    budtenders_by_retailer = {}
    snap_csv = EXPORTS_DIR / "snap_engagement.csv"
    if snap_csv.exists():
        with open(snap_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                retailer = row.get("Retailer", "").strip()
                employee = row.get("Employee", "").strip()
                action = row.get("Action", "").strip()
                if retailer and employee:
                    key = retailer.lower()
                    if key not in budtenders_by_retailer:
                        budtenders_by_retailer[key] = {}
                    if employee not in budtenders_by_retailer[key]:
                        budtenders_by_retailer[key][employee] = {"views": 0, "completions": 0, "ctas": 0}
                    if action == "Story Started":
                        budtenders_by_retailer[key][employee]["views"] += 1
                    elif action == "Story Complete":
                        budtenders_by_retailer[key][employee]["completions"] += 1
                    elif action == "Story Text Question Answer":
                        budtenders_by_retailer[key][employee]["ctas"] += 1

    return {
        "companies_by_name": companies_by_name,
        "companies_by_domain": companies_by_domain,
        "deals_by_company": deals_by_company,
        "budtenders_by_retailer": budtenders_by_retailer,
    }


def fuzzy_match(query: str, candidates: dict, threshold: float = 0.55) -> tuple:
    """Fuzzy match a string against dict keys. Returns (key, score) or (None, 0)."""
    if not query:
        return None, 0
    query_lower = query.lower().strip()
    if query_lower in candidates:
        return query_lower, 1.0

    best_key = None
    best_score = 0
    for key in candidates:
        score = SequenceMatcher(None, query_lower, key).ratio()
        if score > best_score:
            best_score = score
            best_key = key
        # Also check if query is a substring
        if query_lower in key or key in query_lower:
            score = max(score, 0.8)
            if score > best_score:
                best_score = score
                best_key = key

    if best_score >= threshold:
        return best_key, best_score
    return None, 0


def match_company(recipient_email: str, subject: str, body: str, enrichment: dict) -> dict:
    """Match a draft recipient to enrichment data. Returns context dict."""
    context = {
        "company": None,
        "deals": [],
        "budtenders": [],
        "deal_stage": None,
    }

    # 1. Domain match
    domain = recipient_email.split("@")[-1].lower() if "@" in recipient_email else ""
    if domain and domain not in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com"):
        if domain in enrichment["companies_by_domain"]:
            context["company"] = enrichment["companies_by_domain"][domain]

    # 2. Subject/body company name match
    if not context["company"]:
        # Try matching company names from subject
        for name_lower, company in enrichment["companies_by_name"].items():
            name = company.get("name", "")
            if name and name.lower() in subject.lower():
                context["company"] = company
                break
            if name and name.lower() in body.lower()[:500]:
                context["company"] = company
                break

    # 3. Get deals for matched company
    if context["company"]:
        cname = context["company"].get("name", "")
        key, _ = fuzzy_match(cname, enrichment["deals_by_company"])
        if key:
            context["deals"] = enrichment["deals_by_company"][key]
            # Get highest deal stage
            stage_order = ["Closed Won", "First Order Placed", "Verbal Commitment", "Tasting Done", "Sampled", "Contacted", "Hot Lead"]
            for stage in stage_order:
                for d in context["deals"]:
                    if d.get("stage_label") == stage:
                        context["deal_stage"] = stage
                        break
                if context["deal_stage"]:
                    break

    # 4. Get budtender data
    company_name = context["company"].get("name", "") if context["company"] else ""
    search_terms = [company_name, domain.split(".")[0] if domain else ""]
    for term in search_terms:
        if not term:
            continue
        key, score = fuzzy_match(term, enrichment["budtenders_by_retailer"])
        if key:
            bt_data = enrichment["budtenders_by_retailer"][key]
            # Sort by total engagement
            sorted_bts = sorted(bt_data.items(), key=lambda x: sum(x[1].values()), reverse=True)
            context["budtenders"] = [{"name": name, **stats} for name, stats in sorted_bts[:5]]
            break

    return context


def create_gmail_draft(service, to: str, subject: str, body_text: str,
                       cc: str = "jared@atomicfungi.com",
                       sender: str = "giovanni@atomicfungi.com") -> str:
    """Create a Gmail draft. Returns draft ID."""
    import base64
    from email.mime.text import MIMEText

    msg = MIMEText(body_text, "plain")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return draft["id"]


def get_calendar_service():
    """Build authenticated Google Calendar API service."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if GMAIL_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(GMAIL_CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        GMAIL_TOKEN_PATH.write_text(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def create_calendar_event(
    summary: str,
    description: str = "",
    start_date: str = None,
    start_datetime: str = None,
    duration_minutes: int = 30,
    attendees: list[str] = None,
    calendar_id: str = "giovanni@atomicfungi.com",
) -> str:
    """Create a Google Calendar event. Returns event ID.

    Use start_date for all-day events (YYYY-MM-DD) or
    start_datetime for timed events (YYYY-MM-DDTHH:MM:SS-04:00).
    """
    from datetime import datetime as dt, timedelta, timezone as tz
    cal = get_calendar_service()

    event = {"summary": summary, "description": description}

    if start_date:
        event["start"] = {"date": start_date}
        # All-day events: end = next day
        end = dt.strptime(start_date, "%Y-%m-%d") + timedelta(days=1)
        event["end"] = {"date": end.strftime("%Y-%m-%d")}
    elif start_datetime:
        event["start"] = {"dateTime": start_datetime, "timeZone": "America/New_York"}
        # Parse and add duration
        if "T" in start_datetime:
            base = start_datetime[:19]  # strip timezone
            start_dt = dt.strptime(base, "%Y-%m-%dT%H:%M:%S")
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            tz_part = start_datetime[19:] or "-04:00"
            event["end"] = {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S") + tz_part, "timeZone": "America/New_York"}
    else:
        # Default: tomorrow at 10am ET
        tomorrow = dt.now() + timedelta(days=1)
        start = tomorrow.replace(hour=10, minute=0, second=0)
        event["start"] = {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S") + "-04:00", "timeZone": "America/New_York"}
        end = start + timedelta(minutes=duration_minutes)
        event["end"] = {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S") + "-04:00", "timeZone": "America/New_York"}

    if attendees:
        event["attendees"] = [{"email": e} for e in attendees]

    event["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]}

    result = cal.events().insert(calendarId=calendar_id, body=event, sendUpdates="none").execute()
    return result.get("id", "")


def load_prompt_template(name: str) -> str:
    """Load a prompt template from config/ directory."""
    path = CONFIG_PATH / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")
