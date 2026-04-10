# Atomic Fungi Intelligence Platform — Operations Guide

**Last updated:** April 9, 2026

---

## What This System Does

This platform connects Sparkplug (budtender engagement), HubSpot (CRM/deals), Gmail, Google Calendar, and Google Chat into one automated pipeline. It runs daily, keeps your CRM current, drafts emails in your voice, nags you on tasks, and posts updates to your team Chat spaces.

---

## What Runs Automatically (no action needed)

| What | When | Where |
|------|------|-------|
| Sparkplug data export (retailers, sales, Snap engagement, budtender leaderboard) | 8:30 AM ET daily | Windows Task Scheduler |
| HubSpot data export (deals, companies, pipeline) | 8:30 AM ET daily | Same export job |
| Gmail draft count + inbox snapshot | 8:30 AM ET daily | Same export job |
| Google Chat message scan (store visits, team updates) | 8:30 AM ET daily | Same export job |
| Daily Intel email (pipeline, sales, leaderboard, action items, task nags) | 9:00 AM ET daily | Claude remote trigger |
| CRM update posted to AF - CRM Chat | 9:00 AM ET daily | Same trigger |
| Snap engagement update posted to AF - Digital Marketing Chat | 9:00 AM ET daily | Same trigger |
| Inbox cleanup (promotions, social, junk domains trashed) | 9:00 AM ET daily | Same trigger |
| Calendar events created for high-priority action items | 9:00 AM ET daily | Same trigger |

**You don't touch any of this.** It runs every morning. You get the email and Chat posts.

---

## What You Run Manually (when needed)

### After Store Visits
When you and Jared visit stores, run two things:

```bash
# 1. Generate follow-up email drafts (creates Gmail drafts, doesn't send)
python scripts/store_visit_followup.py "Store1, Store2, Store3" --visitor "Giovanni and Jared" --tasting

# 2. Update HubSpot deal stages
#    Edit the STORE_VISITS dict in scripts/update_hubspot_deals.py, then:
python scripts/update_hubspot_deals.py
```

Then go to Gmail and review/send the drafts.

### Outreach Campaigns
When you want to rewrite a batch of outreach drafts in your voice:

```bash
python scripts/rewrite_drafts.py --dry-run --limit 5   # preview first
python scripts/rewrite_drafts.py --limit 20             # rewrite 20 drafts
python scripts/rewrite_drafts.py --skip-existing        # skip already-rewritten ones
```

Creates NEW drafts (originals preserved). Review in Gmail before sending.

### Agent Pipeline (NEW)
Three AI agents that work your inbox:

```bash
# Preview everything first
python scripts/run_agents.py all --dry-run

# Or run individual agents:
python scripts/run_agents.py inbox      # Triages unread email: stars important, archives noise
python scripts/run_agents.py respond    # Drafts replies to starred emails in your voice
python scripts/run_agents.py tasks      # Nags on overdue tasks, creates new tasks from emails

# Full pipeline (runs all three in order)
python scripts/run_agents.py all
```

**Important: Nothing sends automatically.** The respond agent creates drafts. You review and hit send.

### Data Refresh
If you need fresh data outside the daily export:

```bash
python scripts/export_data.py
```

---

## What You Must Do (your jobs)

1. **Review and send email drafts.** The system writes them, you approve them. Check Gmail drafts after running agents or follow-up generators.

2. **Star emails you want replies drafted for.** The auto-respond agent processes starred unread emails. Star something in Gmail, run `python scripts/run_agents.py respond`, check the draft.

3. **Update task status.** When you complete a task, update `scripts/tasks.json` or tell Claude to update it. The task agent nags daily until things are marked done.

4. **Report store visits.** After visiting stores, run the follow-up generator and HubSpot updater. Or just tell Claude in a session and it'll handle it (like we did today).

5. **Refresh the Sparkplug JWT token** every ~30 days. Go to Sparkplug in your browser, open DevTools > Application > Local Storage, copy the JWT, and update `~/.sparkplug/sparkplug.json`.

6. **Review the Daily Intel email.** It tells you what needs attention. Act on the action items.

---

## When Do Responses Get Automated?

### Current State: DRAFT ONLY (Phase 1)
Everything creates drafts. Nothing sends without you clicking send. This is intentional — the system needs to earn trust first.

### Phase 2: Semi-Auto (start when ready)
Once you're confident the drafts consistently match your voice:
- **Auto-send routine replies** (meeting confirmations, "thanks for the samples" follow-ups, simple acknowledgments)
- **Draft-only for substantive emails** (new outreach, pricing discussions, regulatory responses)
- Criteria: You've reviewed ~50 drafts and edited fewer than 10% of them

### Phase 3: Full Auto (future)
- Agents handle entire email categories autonomously
- You get a daily digest of what was sent, not drafts to review
- Override/undo within 30 minutes via Gmail "Undo Send"
- **Never auto-send:** regulatory/government emails, anything involving money, first contact with new people

### How to Move to Phase 2
Tell Claude: "Start auto-sending routine replies." The system will:
1. Add a `gmail_send_draft` tool call after drafting routine replies
2. Tag auto-sent emails with a "Sent by AF Agent" label
3. Include auto-sent emails in the daily digest so you can review

You can pull back to Phase 1 at any time.

---

## Google Chat Spaces

| Space | What Gets Posted | Webhook |
|-------|-----------------|---------|
| AF - CRM | Pipeline updates, stale contacts, deal alerts, action items | Active |
| AF - Digital Marketing | Snap engagement stats, budtender leaderboard, content performance | Active |
| AF - Team Chat | Available but not currently posting daily | Wired up |
| AF - Sample Requests | Available but not currently posting daily | Wired up |

---

## Accounts and Tokens

| Service | Token Location | Expires | Notes |
|---------|---------------|---------|-------|
| Sparkplug JWT | `~/.sparkplug/sparkplug.json` | ~30 days (Jun 22) | Refresh from browser DevTools |
| Gmail OAuth (Giovanni) | `~/.sparkplug/gmail_token.json` | Auto-refreshes | Full access: read, write, send, modify |
| Gmail OAuth (Jared) | `~/.sparkplug/gmail_token_jared.json` | Not set up yet | Needs OAuth flow |
| HubSpot Private App | `~/.sparkplug/hubspot_token.txt` | No expiry | Read + write deals/companies |
| Anthropic API | `~/.sparkplug/anthropic_key.txt` | No expiry | Powers draft rewriting + agents |
| Google Chat webhooks | `config/webhooks.json` | No expiry | 4 spaces configured |

---

## File Structure

```
~/projects/sparkplug-plugin/
├── scripts/
│   ├── agents/                    # AI agent team (NEW)
│   │   ├── tools.py               # 14 MCP tools (Gmail, Calendar, Tasks, HubSpot)
│   │   ├── base.py                # Agent runner (Claude Agent SDK)
│   │   ├── auto_respond.py        # Drafts replies to starred emails
│   │   ├── task_agent.py          # Nags tasks, creates new ones from emails
│   │   └── inbox_agent.py         # Triages inbox: star, archive, categorize
│   ├── run_agents.py              # CLI: run one agent or full pipeline
│   ├── daily_intel.py             # Daily email + Chat pipeline
│   ├── export_data.py             # Sparkplug + HubSpot + Gmail data export
│   ├── rewrite_drafts.py          # Outreach draft rewriter
│   ├── store_visit_followup.py    # Post-visit follow-up generator
│   ├── update_hubspot_deals.py    # Batch deal stage updates
│   ├── email_utils.py             # Shared Gmail/Calendar/LLM utilities
│   └── tasks.json                 # Task tracker (label redesign project)
├── config/
│   ├── rewrite_prompt.txt         # Giovanni's voice prompt
│   ├── gold_standard_email.txt    # Craft Collective email (tone reference)
│   ├── sent_examples.txt          # More tone references
│   ├── webhooks.json              # Google Chat webhook URLs
│   └── followup_prompt.txt        # Store visit follow-up prompt
├── exports/                       # Daily data snapshots (JSON/CSV)
└── servers/                       # MCP server (Sparkplug API client)
```

---

## Quick Reference

| I want to... | Run this |
|--------------|----------|
| See what the agents would do | `python scripts/run_agents.py all --dry-run` |
| Process my inbox | `python scripts/run_agents.py inbox` |
| Get reply drafts for starred emails | `python scripts/run_agents.py respond` |
| Check task status | `python scripts/run_agents.py tasks --no-email-scan` |
| Generate store visit follow-ups | `python scripts/store_visit_followup.py "stores" --visitor Name --tasting` |
| Rewrite outreach drafts | `python scripts/rewrite_drafts.py --limit 10` |
| Update HubSpot deal stages | Edit + run `python scripts/update_hubspot_deals.py` |
| Refresh all data | `python scripts/export_data.py` |
| See today's intel without email | `python scripts/daily_intel.py --dry-run` |
