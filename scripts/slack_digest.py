#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the daily batch as a Slack-ready markdown message and print it to stdout.

This script does NOT talk to Slack. Posting is done by the Claude routine through
the Slack connector (same path as the BDR Agent: the message appears as the user,
"Sent using @Claude"), so no bot, no app and no token are needed anywhere.

   python3 scripts/slack_digest.py [--date 2026-09-02] [--format table|code]

--format table (default) uses a markdown table, which slack_send_message converts
into a real Slack table. NOTE: the draft composer does NOT convert tables, so a
draft will show raw pipes even though the sent message renders correctly.
--format code emits a fixed-width code block instead: renders identically
everywhere, including drafts, at the cost of not being clickable.

Reads Supabase directly - both the rows and the funnel stats - so the routine can
run on any machine, hours after the scan, with no shared filesystem.
Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, PORTAL_BASE_URL (optional)
"""
import json, os, sys, datetime, urllib.parse, urllib.request

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


def main(date=None, fmt="table"):
    today = datetime.date.fromisoformat(date) if date else datetime.date.today()
    q = urllib.parse.urlencode({
        "select": "*", "batch_date": f"eq.{today.isoformat()}",
        "order": "score.desc,deadline.asc"})
    rows = rest(f"rfps?{q}")
    batch = rest(f"rfp_batches?batch_date=eq.{today.isoformat()}&select=*")
    stats = batch[0] if batch else {}
    print(render(rows, stats, today, fmt))


if __name__ == "__main__":
    d = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else None
    f = sys.argv[sys.argv.index("--format") + 1] if "--format" in sys.argv else "table"
    main(d, f)
