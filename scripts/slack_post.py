#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post the daily batch to #rfp-agent, in the same format as the BDR Agent.
   python3 scripts/slack_post.py data/saved_2026-09-02.json [--stats stats.json]
Env: SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, PORTAL_BASE_URL
"""
import json, os, sys, datetime, urllib.request

TOKEN   = os.environ["SLACK_BOT_TOKEN"]
CHANNEL = os.environ["SLACK_CHANNEL_ID"]
PORTAL  = os.environ.get("PORTAL_BASE_URL", "").rstrip("/")
API     = "https://slack.com/api/chat.postMessage"
MAX_ROWS = 25          # the rest continues in the thread, like the BDR Agent does

def api(payload):
    req = urllib.request.Request(API, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=45) as r:
        d = json.load(r)
    if not d.get("ok"): raise SystemExit(f"Slack rejected the message: {d.get('error')}")
    return d

def days_left(deadline):
    if not deadline: return "—"
    try:
        n = (datetime.date.fromisoformat(deadline[:10]) - datetime.date.today()).days
        return f"{n}d" if n >= 0 else "expired"
    except ValueError:
        return "—"

def table_block(rows):
    """Slack native table block: max 100 rows x 20 columns."""
    head = ["#", "Notice", "Buyer", "Country", "Score", "Deadline", "Left", "Portal"]
    def cell(t): return {"type": "raw_text", "text": str(t)[:180]}
    trs = [[cell(h) for h in head]]
    for i, r in enumerate(rows, 1):
        link = f"{PORTAL}/rfp/{r['id']}" if PORTAL else (r.get("url") or "")
        trs.append([
            cell(i),
            cell((r.get("title") or "")[:70]),
            cell((r.get("buyer") or "—")[:38]),
            cell(r.get("buyer_country") or "—"),
            cell(f"{float(r.get('score') or 0):.0f}"),
            cell((r.get("deadline") or "—")[:10]),
            cell(days_left(r.get("deadline"))),
            {"type": "rich_text", "elements": [{"type": "rich_text_section",
                "elements": [{"type": "link", "url": link, "text": "open"}]}]}
            if link else cell("—"),
        ])
    return {"type": "table", "rows": trs}

def build(rows, stats):
    today = datetime.date.today().isoformat()
    hot  = [r for r in rows if r["tier"] == "HOT"]
    warm = [r for r in rows if r["tier"] == "WARM"]
    dq   = [r for r in rows if r.get("disqualified")]
    live = [r for r in rows if not r.get("disqualified")]
    avg  = (sum(float(r["score"]) for r in rows) / len(rows)) if rows else 0
    soon = [r for r in live if r.get("deadline") and
            0 <= (datetime.date.fromisoformat(r["deadline"][:10]) - datetime.date.today()).days <= 14]

    head = (f":satellite_antenna: _New RFP Batch — {today}_\n"
            f"RFPs saved: _{len(rows)}_ · HOT (≥60): _{len(hot)}_ · WARM: _{len(warm)}_ · "
            f"Disqualified: _{len(dq)}_ · Avg score: _{avg:.1f}_ · Window: {stats.get('days', 3)} days")

    prov = (f"_Scanned {stats.get('scanned', 0):,} notices "
            f"(DE Datenservice {stats.get('scanned_de', 0):,} + TED/EU {stats.get('scanned_ted', 0):,}) · "
            f"CPV matched: {stats.get('by_cpv', 0)} · full-text only: {stats.get('by_fulltext', 0)} · "
            f"new since last run: {len(rows)}_")

    blocks = [{"type": "markdown", "text": head}, {"type": "markdown", "text": prov}]
    if soon:
        blocks.append({"type": "markdown", "text":
            f":warning: _{len(soon)} with a deadline inside 14 days — decide bid/no-bid this week._"})
    shown = live[:MAX_ROWS]
    if shown:
        blocks.append(table_block(shown))
    else:
        blocks.append({"type": "markdown",
                       "text": "_No new opportunities within the criteria in this window._"})

    cont = (f"…table continues in thread ({MAX_ROWS+1}–{len(live)}) · " if len(live) > MAX_ROWS else "")
    foot = f"_{cont}full batch in Supabase `rfps` ·_ :satellite_antenna: _RFP Radar_"
    if dq:
        foot = (f"_{len(dq)} disqualified by the technical screen "
                f"({dq[0].get('disqualification_reason','')[:60]}…) — see `rfps` ·_\n") + foot
    blocks.append({"type": "markdown", "text": foot})
    return blocks, head, live

def main(path, stats_path=None):
    rows = json.load(open(path))
    stats = json.load(open(stats_path)) if stats_path and os.path.exists(stats_path) else {}
    blocks, fallback, live = build(rows, stats)
    try:
        d = api({"channel": CHANNEL, "blocks": blocks, "text": fallback})
    except SystemExit:                       # table block rejected: fall back to text
        d = api({"channel": CHANNEL, "text": fallback +
                 "\n\n(table unavailable — see Supabase `rfps`)"})
    print(f"[slack] posted ts={d['ts']}")
    if len(live) > MAX_ROWS:                 # remainder in the thread, like the BDR Agent
        api({"channel": CHANNEL, "thread_ts": d["ts"],
             "blocks": [table_block(live[MAX_ROWS:])],
             "text": f"RFPs {MAX_ROWS+1}–{len(live)}"})
    return d

if __name__ == "__main__":
    s = sys.argv[sys.argv.index("--stats") + 1] if "--stats" in sys.argv else None
    main(sys.argv[1], s)
