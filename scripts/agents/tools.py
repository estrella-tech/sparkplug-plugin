"""
Shared MCP tools for Atomic Fungi agents.
Gmail, Calendar, Tasks, and HubSpot enrichment — all run in-process.
"""

import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path
from typing import Annotated

from claude_agent_sdk import tool

sys.path.insert(0, str(Path(__file__).parent.parent))
from email_utils import (
    get_gmail_service,
    get_calendar_service,
    load_enrichment_data,
    match_company,
    load_prompt_template,
    CONFIG_DIR,
    EXPORTS_DIR,
)

TASKS_PATH = Path(__file__).parent.parent / "tasks.json"


# ---------------------------------------------------------------------------
# Gmail tools
# ---------------------------------------------------------------------------

@tool(
    "gmail_search",
    "Search Gmail messages. Returns id, from, to, subject, snippet for each result.",
    {"query": Annotated[str, "Gmail search query (e.g. 'is:starred is:unread', 'from:someone@example.com')"],
     "max_results": Annotated[int, "Max messages to return (default 10)"]},
)
async def gmail_search(args):
    svc = get_gmail_service()
    q = args["query"]
    limit = args.get("max_results", 10)
    resp = svc.users().messages().list(userId="me", q=q, maxResults=limit).execute()
    messages = []
    for m in resp.get("messages", []):
        full = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                          metadataHeaders=["From", "To", "Subject", "Date"]).execute()
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        messages.append({
            "id": m["id"],
            "threadId": full.get("threadId"),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": full.get("snippet", ""),
            "labels": full.get("labelIds", []),
        })
    return {"content": [{"type": "text", "text": json.dumps(messages, indent=2)}]}


@tool(
    "gmail_read",
    "Read the full body of a Gmail message by ID.",
    {"message_id": Annotated[str, "Gmail message ID"]},
)
async def gmail_read(args):
    svc = get_gmail_service()
    full = svc.users().messages().get(userId="me", id=args["message_id"], format="full").execute()
    headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
    # Extract body
    body = ""
    payload = full.get("payload", {})
    if payload.get("body", {}).get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    else:
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break
            # Check nested parts
            for subpart in part.get("parts", []):
                if subpart.get("mimeType") == "text/plain" and subpart.get("body", {}).get("data"):
                    body = base64.urlsafe_b64decode(subpart["body"]["data"]).decode("utf-8", errors="replace")
                    break
    result = {
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "body": body[:5000],
    }
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "gmail_create_draft",
    "Create a Gmail draft. Returns the draft ID.",
    {"to": Annotated[str, "Recipient email"],
     "subject": Annotated[str, "Email subject"],
     "body": Annotated[str, "Plain text email body"],
     "cc": Annotated[str, "CC recipients (optional)"]},
)
async def gmail_create_draft(args):
    svc = get_gmail_service()
    msg = MIMEText(args["body"], "plain")
    msg["From"] = "giovanni@atomicfungi.com"
    msg["To"] = args["to"]
    msg["Subject"] = args["subject"]
    cc = args.get("cc", "")
    if cc:
        msg["Cc"] = cc
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = svc.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return {"content": [{"type": "text", "text": f"Draft created: {draft['id']}"}]}


@tool(
    "gmail_send_draft",
    "Send an existing Gmail draft by its draft ID.",
    {"draft_id": Annotated[str, "Gmail draft ID to send"]},
)
async def gmail_send_draft(args):
    svc = get_gmail_service()
    sent = svc.users().drafts().send(userId="me", body={"id": args["draft_id"]}).execute()
    return {"content": [{"type": "text", "text": f"Sent message: {sent.get('id', 'unknown')}"}]}


@tool(
    "gmail_check_prior_contact",
    "Check if we've previously emailed a domain/address. Returns count and snippets of sent emails.",
    {"email_or_domain": Annotated[str, "Email address or domain to check"]},
)
async def gmail_check_prior_contact(args):
    svc = get_gmail_service()
    target = args["email_or_domain"]
    # Search sent mail
    resp = svc.users().messages().list(
        userId="me", q=f"from:me to:{target} is:sent", maxResults=5
    ).execute()
    sent = resp.get("messages", [])
    results = []
    for m in sent[:5]:
        full = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                          metadataHeaders=["To", "Subject", "Date"]).execute()
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        results.append({
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": full.get("snippet", ""),
        })
    output = {"prior_contact": len(sent) > 0, "count": len(sent), "sent_emails": results}
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2)}]}


@tool(
    "gmail_modify_labels",
    "Add or remove labels on a Gmail message (e.g. archive, star, mark read).",
    {"message_id": Annotated[str, "Gmail message ID"],
     "add_labels": Annotated[str, "Comma-separated label IDs to add (e.g. STARRED,IMPORTANT)"],
     "remove_labels": Annotated[str, "Comma-separated label IDs to remove (e.g. INBOX,UNREAD)"]},
)
async def gmail_modify_labels(args):
    svc = get_gmail_service()
    add = [l.strip() for l in args.get("add_labels", "").split(",") if l.strip()]
    remove = [l.strip() for l in args.get("remove_labels", "").split(",") if l.strip()]
    body = {}
    if add:
        body["addLabelIds"] = add
    if remove:
        body["removeLabelIds"] = remove
    svc.users().messages().modify(userId="me", id=args["message_id"], body=body).execute()
    return {"content": [{"type": "text", "text": f"Labels updated on {args['message_id']}"}]}


# ---------------------------------------------------------------------------
# Calendar tools
# ---------------------------------------------------------------------------

@tool(
    "calendar_list_events",
    "List upcoming calendar events. Returns summary, start, end, attendees.",
    {"days_ahead": Annotated[int, "Number of days to look ahead (default 7)"],
     "max_results": Annotated[int, "Max events to return (default 20)"]},
)
async def calendar_list_events(args):
    cal = get_calendar_service()
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=args.get("days_ahead", 7))
    events_result = cal.events().list(
        calendarId="giovanni@atomicfungi.com",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        maxResults=args.get("max_results", 20),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = []
    for e in events_result.get("items", []):
        events.append({
            "id": e.get("id"),
            "summary": e.get("summary", ""),
            "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
            "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
            "attendees": [a.get("email") for a in e.get("attendees", [])],
            "location": e.get("location", ""),
        })
    return {"content": [{"type": "text", "text": json.dumps(events, indent=2)}]}


@tool(
    "calendar_find_free_slots",
    "Find free time slots in Giovanni's calendar for a given date.",
    {"date": Annotated[str, "Date to check (YYYY-MM-DD)"],
     "duration_minutes": Annotated[int, "Meeting duration in minutes (default 30)"]},
)
async def calendar_find_free_slots(args):
    cal = get_calendar_service()
    date_str = args["date"]
    duration = args.get("duration_minutes", 30)
    # Business hours 9 AM - 5 PM ET
    start = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=9, minute=0)
    end = start.replace(hour=17, minute=0)
    tz_offset = "-04:00"  # ET
    events_result = cal.events().list(
        calendarId="giovanni@atomicfungi.com",
        timeMin=f"{start.strftime('%Y-%m-%dT%H:%M:%S')}{tz_offset}",
        timeMax=f"{end.strftime('%Y-%m-%dT%H:%M:%S')}{tz_offset}",
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    busy = []
    for e in events_result.get("items", []):
        s = e.get("start", {}).get("dateTime", "")
        en = e.get("end", {}).get("dateTime", "")
        if s and en:
            busy.append((s, en))
    # Find gaps
    slots = []
    current = start
    for bs, be in sorted(busy):
        busy_start = datetime.fromisoformat(bs).replace(tzinfo=None)
        busy_end = datetime.fromisoformat(be).replace(tzinfo=None)
        if busy_start > current and (busy_start - current).total_seconds() >= duration * 60:
            slots.append(f"{current.strftime('%I:%M %p')} - {busy_start.strftime('%I:%M %p')}")
        current = max(current, busy_end)
    if current < end:
        slots.append(f"{current.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}")
    result = {"date": date_str, "free_slots": slots, "busy_count": len(busy)}
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "calendar_create_event",
    "Create a Google Calendar event.",
    {"summary": Annotated[str, "Event title"],
     "date": Annotated[str, "Date (YYYY-MM-DD) for all-day, or YYYY-MM-DDTHH:MM:SS-04:00 for timed"],
     "duration_minutes": Annotated[int, "Duration in minutes (default 30, ignored for all-day)"],
     "description": Annotated[str, "Event description (optional)"],
     "attendees": Annotated[str, "Comma-separated attendee emails (optional)"]},
)
async def calendar_create_event(args):
    from email_utils import create_calendar_event
    attendee_list = [e.strip() for e in args.get("attendees", "").split(",") if e.strip()] or None
    is_timed = "T" in args["date"]
    event_id = create_calendar_event(
        summary=args["summary"],
        description=args.get("description", ""),
        start_datetime=args["date"] if is_timed else None,
        start_date=args["date"] if not is_timed else None,
        duration_minutes=args.get("duration_minutes", 30),
        attendees=attendee_list,
    )
    return {"content": [{"type": "text", "text": f"Event created: {event_id}"}]}


# ---------------------------------------------------------------------------
# Task tools
# ---------------------------------------------------------------------------

def _load_tasks_file() -> dict:
    if TASKS_PATH.exists():
        return json.loads(TASKS_PATH.read_text())
    return {"projects": {}, "tasks": []}


def _save_tasks_file(data: dict):
    TASKS_PATH.write_text(json.dumps(data, indent=2))


@tool(
    "tasks_list",
    "List all tasks from tasks.json. Shows status, priority, due date, overdue status.",
    {"status_filter": Annotated[str, "Filter by status: open, in_progress, completed, blocked, all (default: all)"]},
)
async def tasks_list(args):
    data = _load_tasks_file()
    tasks = data.get("tasks", [])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filt = args.get("status_filter", "all")
    results = []
    for t in tasks:
        if filt != "all" and t["status"] != filt:
            continue
        overdue = False
        days_overdue = 0
        if t["status"] in ("open", "in_progress") and t.get("due"):
            overdue = t["due"] < today
            if overdue:
                days_overdue = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(t["due"], "%Y-%m-%d")).days
        results.append({
            **t,
            "overdue": overdue,
            "days_overdue": days_overdue,
        })
    return {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}


@tool(
    "tasks_create",
    "Create a new task in tasks.json.",
    {"title": Annotated[str, "Task title"],
     "project": Annotated[str, "Project key (e.g. label_redesign)"],
     "priority": Annotated[str, "Priority: critical, high, medium, low"],
     "due": Annotated[str, "Due date YYYY-MM-DD (optional)"],
     "notes": Annotated[str, "Additional notes (optional)"]},
)
async def tasks_create(args):
    data = _load_tasks_file()
    # Generate ID
    existing_ids = [t["id"] for t in data.get("tasks", [])]
    prefix = args["project"].split("_")[0] if "_" in args["project"] else args["project"][:5]
    num = 1
    while f"{prefix}-{num:02d}" in existing_ids:
        num += 1
    task_id = f"{prefix}-{num:02d}"
    new_task = {
        "id": task_id,
        "project": args["project"],
        "title": args["title"],
        "priority": args.get("priority", "medium"),
        "status": "open",
        "due": args.get("due"),
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "last_nagged": None,
        "nag_count": 0,
        "notes": args.get("notes", ""),
    }
    data.setdefault("tasks", []).append(new_task)
    _save_tasks_file(data)
    return {"content": [{"type": "text", "text": f"Task created: {task_id} — {args['title']}"}]}


@tool(
    "tasks_update",
    "Update a task's status, priority, due date, or notes.",
    {"task_id": Annotated[str, "Task ID (e.g. label-01)"],
     "status": Annotated[str, "New status: open, in_progress, completed, blocked (optional)"],
     "priority": Annotated[str, "New priority (optional)"],
     "due": Annotated[str, "New due date YYYY-MM-DD (optional)"],
     "notes": Annotated[str, "Append to notes (optional)"]},
)
async def tasks_update(args):
    data = _load_tasks_file()
    for t in data.get("tasks", []):
        if t["id"] == args["task_id"]:
            if args.get("status"):
                t["status"] = args["status"]
            if args.get("priority"):
                t["priority"] = args["priority"]
            if args.get("due"):
                t["due"] = args["due"]
            if args.get("notes"):
                t["notes"] = (t.get("notes", "") + "\n" + args["notes"]).strip()
            _save_tasks_file(data)
            return {"content": [{"type": "text", "text": f"Task {args['task_id']} updated: {json.dumps(t, indent=2)}"}]}
    return {"content": [{"type": "text", "text": f"Task {args['task_id']} not found"}], "is_error": True}


@tool(
    "tasks_nag",
    "Record that a task was nagged today. Increments nag_count and sets last_nagged.",
    {"task_id": Annotated[str, "Task ID to mark as nagged"]},
)
async def tasks_nag(args):
    data = _load_tasks_file()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for t in data.get("tasks", []):
        if t["id"] == args["task_id"]:
            t["last_nagged"] = today
            t["nag_count"] = t.get("nag_count", 0) + 1
            _save_tasks_file(data)
            return {"content": [{"type": "text", "text": f"Nagged {args['task_id']} (count: {t['nag_count']})"}]}
    return {"content": [{"type": "text", "text": f"Task {args['task_id']} not found"}], "is_error": True}


# ---------------------------------------------------------------------------
# Enrichment tools
# ---------------------------------------------------------------------------

@tool(
    "lookup_company",
    "Look up a company in HubSpot + Sparkplug data by name or email domain. Returns deals, budtender engagement, last contact.",
    {"query": Annotated[str, "Company name or email address to look up"]},
)
async def lookup_company(args):
    enrichment = load_enrichment_data()
    q = args["query"]
    # If it looks like an email, extract domain
    if "@" in q:
        domain = q.split("@")[-1]
        email = q
    else:
        domain = ""
        email = ""
    context = match_company(email or f"x@{q}", q, q, enrichment)
    result = {
        "company": context["company"],
        "deals": context["deals"],
        "deal_stage": context["deal_stage"],
        "budtenders": context["budtenders"],
    }
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]}


# ---------------------------------------------------------------------------
# Tool collections
# ---------------------------------------------------------------------------

GMAIL_TOOLS = [gmail_search, gmail_read, gmail_create_draft, gmail_send_draft,
               gmail_check_prior_contact, gmail_modify_labels]

CALENDAR_TOOLS = [calendar_list_events, calendar_find_free_slots, calendar_create_event]

TASK_TOOLS = [tasks_list, tasks_create, tasks_update, tasks_nag]

ENRICHMENT_TOOLS = [lookup_company]

ALL_TOOLS = GMAIL_TOOLS + CALENDAR_TOOLS + TASK_TOOLS + ENRICHMENT_TOOLS
