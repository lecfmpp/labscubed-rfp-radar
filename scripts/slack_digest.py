#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the daily batch as a Slack-ready markdown message and print it to stdout.

If a Slack credential is set (SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN), the script
POSTS the digest to #rfp-agent itself — this is how the GitHub Actions run
publishes, with no local machine. With neither set it just prints to stdout, so
a Claude connector or a human can post the same message (the original path).

   python3 scripts/slack_digest.py [--date 2026-09-02] [--format table|code]

--format table (default) uses a markdown table, which the Slack CONNECTOR renders
as a real table. A bot/webhook post does NOT render markdown tables, so the
GitHub Actions step calls --format code.
--format code emits a fixed-width code block instead: renders identically
everywhere (bot, webhook, draft), at the cost of the table cells not being links.

Reads Supabase directly - both the rows and the funnel stats - so it can run on
any machine, hours after the scan, with no shared filesystem.
Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, PORTAL_BASE_URL (optional),
     SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN (+ SLACK_CHANNEL, default #rfp-agent)
"""
import json, os, sys, re, datetime, urllib.parse, urllib.request

URL    = os.environ["SUPABASE_URL"].rstrip("/")
KEY    = os.environ["SUPABASE_SERVICE_KEY"]
PORTAL = os.environ.get("PORTAL_BASE_URL", "").rstrip("/")
MAX_ROWS = 25          # the rest continues in the thread, like the BDR Agent does


def rest(path):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers={
        "apikey": KEY, "Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def days_left(deadline, today):
    if not deadline: return "—"
    try:
        n = (datetime.date.fromisoformat(deadline[:10]) - today).days
        return f"{n}d" if n >= 0 else "expired"
    except ValueError:
        return "—"


def esc(t):
    """Escape only literal pipes; the structural ones build the table."""
    return (t or "").replace("|", "\\|").replace("\n", " ").strip()


def clean_title(raw):
    """Pull the real subject out of a long OJEU/TED title (country – CPV category
    – ref codes – procedure – SUBJECT), mirroring the portal's parseTitle, so the
    Slack card headlines the thing being bought rather than the whole string."""
    t = (raw or "").strip()
    m = re.search(r'(?:for the (?:supply|provision|purchase|delivery|procurement) of'
                  r'|procedure for the (?:supply|provision) of|supply of|provision of'
                  r'|purchase of|procurement of|delivery of|contract for|tender for'
                  r'|framework (?:agreement )?for)\s+(.+)$', t, re.I)
    if m and len(m.group(1).strip()) > 8:
        s = re.sub(r'^the\s+', '', m.group(1).strip(), flags=re.I)
    else:
        parts = re.split(r'\s+[\u2013\u2014]\s+', t)   # en / em dash
        s = parts[-1].strip() if len(parts) > 1 and len(parts[-1].strip()) > 12 else t
    return (s[:1].upper() + s[1:]) if s else t


def render(rows, stats, today, fmt="table"):
    hot  = [r for r in rows if r["tier"] == "HOT"]
    warm = [r for r in rows if r["tier"] == "WARM"]
    dq   = [r for r in rows if r.get("disqualified")]
    live = [r for r in rows if not r.get("disqualified")]
    avg  = (sum(float(r["score"]) for r in rows) / len(rows)) if rows else 0
    soon = [r for r in live if r.get("deadline")
            and 0 <= (datetime.date.fromisoformat(r["deadline"][:10]) - today).days <= 14]

    out = [
        f":satellite_antenna: _New RFP Batch — {today}_",
        f"RFPs saved: _{len(rows)}_ · HOT (≥60): _{len(hot)}_ · WARM: _{len(warm)}_ · "
        f"Disqualified: _{len(dq)}_ · Avg score: _{avg:.1f}_ · Window: {stats.get('days', 3)} days",
        "",
        f"_Scanned {stats.get('scanned', 0):,} notices "
        f"(DE Datenservice {stats.get('scanned_de', 0):,} + TED/EU {stats.get('scanned_ted', 0):,}) · "
        f"CPV matched: {stats.get('by_cpv', 0)} · full-text only: {stats.get('by_fulltext', 0)} · "
        f"new since last run: {len(rows)}_",
        "",
    ]
    if soon:
        out += [f":warning: _{len(soon)} with a deadline inside 14 days — "
                f"decide bid/no-bid this week._", ""]

    shown = live[:MAX_ROWS]
    if shown and fmt == "code":
        # Fixed-width block: renders the same everywhere, drafts included.
        w = (3, 52, 30, 5, 6, 12, 6)
        head = ("#", "Notice", "Buyer", "Ctry", "Score", "Deadline", "Left")
        lines = ["  ".join(h.ljust(x) for h, x in zip(head, w)).rstrip(),
                 "  ".join("-" * x for x in w)]
        for i, r in enumerate(shown, 1):
            flag = "*" if r.get("deadline_is_proxy") and r.get("deadline") else ""
            lines.append("  ".join([
                str(i).ljust(w[0]), esc(r.get("title"))[:w[1]].ljust(w[1]),
                (esc(r.get("buyer")) or "-")[:w[2]].ljust(w[2]),
                (r.get("buyer_country") or "-").ljust(w[3]),
                f"{float(r.get('score') or 0):.0f}".ljust(w[4]),
                ((r.get("deadline") or "-")[:10] + flag).ljust(w[5]),
                days_left(r.get("deadline"), today).ljust(w[6]),
            ]).rstrip())
        out += ["```", *lines, "```", ""]
        for i, r in enumerate(shown, 1):
            link = f"{PORTAL}/rfp/{r['id']}" if PORTAL else (r.get("url") or "")
            if link: out.append(f"{i}. <{link}|{esc(r.get('title'))[:60]}>")
        out.append("")
    elif shown:
        out += ["| # | Notice | Buyer | Country | Score | Deadline | Left | Link |",
                "|---|---|---|---|---|---|---|---|"]
        for i, r in enumerate(shown, 1):
            link = f"{PORTAL}/rfp/{r['id']}" if PORTAL else (r.get("url") or "")
            cell = f"[open]({link})" if link else "—"
            flag = " ⚠️" if r.get("deadline_is_proxy") and r.get("deadline") else ""
            out.append(
                f"| {i} | {esc(r.get('title'))[:70]} | {esc(r.get('buyer'))[:38] or '—'} "
                f"| {r.get('buyer_country') or '—'} | {float(r.get('score') or 0):.0f} "
                f"| {(r.get('deadline') or '—')[:10]}{flag} "
                f"| {days_left(r.get('deadline'), today)} | {cell} |")
        out.append("")
        if any(r.get("deadline_is_proxy") and r.get("deadline") for r in shown):
            mark = "*" if fmt == "code" else "⚠️"
            out += [f"_{mark} = deadline is a proxy (public opening date); confirm on the "
                    "notice page before planning._", ""]
    else:
        out += ["_No new opportunities within the criteria in this window._", ""]

    cont = (f"…table continues in thread ({MAX_ROWS+1}–{len(live)}) · "
            if len(live) > MAX_ROWS else "")
    if dq:
        out.append(f"_{len(dq)} disqualified by the technical screen "
                   f"({esc(dq[0].get('disqualification_reason'))[:60]}) — see `rfps` ·_")
    out.append(f"_{cont}full batch in Supabase `rfps` ·_ :satellite_antenna: _RFP Radar_")
    return "\n".join(out)


def post_slack(text, blocks=None):
    """Post to Slack when running unattended (GitHub Actions). Sends Block Kit
    `blocks` (rich cards) when given, with `text` as the notification fallback.
    Prefers a bot token (chat.postMessage), else an incoming webhook. Returns
    True if a post was attempted. With neither set, the caller prints instead —
    so a human/Claude connector can still post the same message."""
    token   = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL", "C0BUL9KGD52")   # #rfp-agent
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    payload = {"text": text, "unfurl_links": False, "unfurl_media": False}
    if blocks:
        payload["blocks"] = blocks
    if token:
        payload["channel"] = channel
        req = urllib.request.Request("https://slack.com/api/chat.postMessage",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.load(r)
        if not resp.get("ok"):
            raise RuntimeError("Slack chat.postMessage failed: " + str(resp.get("error")))
        return True
    if webhook:
        req = urllib.request.Request(webhook, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        return True
    return False


def render_blocks(rows, stats, today):
    """Slack Block Kit version of the digest: a header, funnel stats, then one
    card per tender with scannable columns and an 'Open' button that deep-links
    to that RFP in the portal. Renders natively (bot OR webhook) — unlike a
    markdown table, which only the Slack connector converts."""
    live = [r for r in rows if not r.get("disqualified")]
    hot  = [r for r in rows if r.get("tier") == "HOT"]
    warm = [r for r in rows if r.get("tier") == "WARM"]
    dq   = [r for r in rows if r.get("disqualified")]
    avg  = (sum(float(r["score"]) for r in rows) / len(rows)) if rows else 0
    soon = [r for r in live if r.get("deadline")
            and 0 <= (datetime.date.fromisoformat(r["deadline"][:10]) - today).days <= 14]

    def deadline_cell(r):
        if r.get("deadline_is_proxy") and r.get("deadline"):
            return ":warning: To be confirmed"
        if r.get("deadline"):
            return f"{r['deadline'][:10]}  ({days_left(r.get('deadline'), today)})"
        return "—"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"\U0001F4E1 New RFP Batch — {today}", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn",
            "text": f"*{len(rows)}* saved  ·  *{len(hot)}* HOT  ·  *{len(warm)}* WARM  ·  "
                    f"*{len(dq)}* disqualified  ·  avg fit *{avg:.0f}*  ·  window {stats.get('days', 3)}d"}]},
        {"type": "context", "elements": [{"type": "mrkdwn",
            "text": f"Scanned {stats.get('scanned', 0):,} notices (DE {stats.get('scanned_de', 0):,} + "
                    f"TED/EU {stats.get('scanned_ted', 0):,})  ·  CPV matched {stats.get('by_cpv', 0)}  ·  "
                    f"full-text {stats.get('by_fulltext', 0)}"}]},
    ]
    if soon:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f":warning:  *{len(soon)} with a deadline inside 14 days* — decide bid/no-bid this week."}})
    blocks.append({"type": "divider"})

    shown = live[:15]   # Block Kit tops out at 50 blocks; the rest is in the portal
    for i, r in enumerate(shown, 1):
        title = clean_title(r.get("title"))[:140]
        link  = f"{PORTAL}/rfp/{r['id']}" if PORTAL else (r.get("url") or "")
        sec = {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{i}. {title}*"},
            "fields": [
                {"type": "mrkdwn", "text": f"*Fit*\n{float(r.get('score') or 0):.0f}  ·  {r.get('tier') or '—'}"},
                {"type": "mrkdwn", "text": f"*Deadline*\n{deadline_cell(r)}"},
                {"type": "mrkdwn", "text": f"*Buyer*\n{(r.get('buyer') or '—')[:60]}"},
                {"type": "mrkdwn", "text": f"*Country*\n{r.get('buyer_country') or '—'}"},
            ],
        }
        if link:
            sec["accessory"] = {"type": "button", "text": {"type": "plain_text", "text": "Open ↗", "emoji": True},
                                "url": link, "action_id": f"open_{i}"}
        blocks.append(sec)
        blocks.append({"type": "divider"})

    if not shown:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": "_No new opportunities within the criteria in this window._"}})

    foot = ":satellite_antenna: RFP Radar  ·  full batch in the portal → Sales · RFPs"
    if len(live) > len(shown):
        foot = f"+{len(live) - len(shown)} more in the portal  ·  " + foot
    if dq:
        foot = f"{len(dq)} disqualified ({(dq[0].get('disqualification_reason') or '')[:50]})  ·  " + foot
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": foot}]})
    return blocks


def log_run(status, rows_affected, note=""):
    """Best-effort automation_runs insert; never fail the job on logging."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        body = json.dumps([{"project": "rfp-radar", "task": "slack-digest",
            "status": status, "rows_affected": rows_affected,
            "notes": note or None, "started_at": now, "completed_at": now}]).encode()
        req = urllib.request.Request(f"{URL}/rest/v1/automation_runs", data=body,
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        print("automation_runs log failed:", e, file=sys.stderr)


def main(date=None, fmt="table"):
    today = datetime.date.fromisoformat(date) if date else datetime.date.today()
    q = urllib.parse.urlencode({
        "select": "*", "batch_date": f"eq.{today.isoformat()}",
        "order": "score.desc,deadline.asc"})
    rows = rest(f"rfps?{q}")
    batch = rest(f"rfp_batches?batch_date=eq.{today.isoformat()}&select=*")
    stats = batch[0] if batch else {}
    live_n = len([r for r in rows if not r.get("disqualified")])
    # Never invent a row: no batch today means the scan did not run — say so
    # instead of posting a zeroed digest that looks like a real quiet day.
    if batch:
        msg = render(rows, stats, today, fmt)          # text (connector / stdout)
        blocks = render_blocks(rows, stats, today)     # Block Kit (bot / webhook)
        fallback = f":satellite_antenna: New RFP Batch — {today}: {live_n} tenders"
    else:
        msg = (f":satellite_antenna: _RFP Radar — {today}_\n"
               "_No batch recorded for today — the 06:00 UTC scan may not have run. "
               "Check `lecfmpp/labscubed-rfp-radar` → Actions → RFP Radar._")
        blocks = None
        fallback = msg
    if post_slack(fallback if blocks else msg, blocks):
        log_run("success" if batch else "partial", live_n,
                "posted digest" if batch else "no batch for today")
    else:
        print(msg)   # no Slack creds: print so a connector/human can post it


if __name__ == "__main__":
    d = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else None
    f = sys.argv[sys.argv.index("--format") + 1] if "--format" in sys.argv else "table"
    main(d, f)
