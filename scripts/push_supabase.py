#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Push the radar batch into Supabase (rfps table) and log it in automation_runs.
   python3 scripts/push_supabase.py data/radar_2026-09-02.json
Env: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import json, os, sys, datetime, urllib.request, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from score import disqualify

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
     "Content-Type": "application/json"}

def rest(method, path, payload=None, prefer=None):
    h = dict(H)
    if prefer: h["Prefer"] = prefer
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        return json.loads(body) if body else []

def to_row(r, batch):
    dq, why = disqualify(r.get("title", ""), r.get("description", "") or r.get("why", ""))
    return {
        "source": r["source"], "notice_id": str(r["id"]),
        "procedure_id": r.get("procedure"), "url": r.get("url"),
        "title": (r.get("title") or "")[:1000], "description": r.get("description"),
        "buyer": r.get("buyer"), "buyer_city": r.get("city"),
        "buyer_country": (r.get("country") if isinstance(r.get("country"), str)
                          else ", ".join(r.get("country") or [])) or None,
        "cpv": [c[:8] for c in (r.get("cpv") or [])],
        "notice_type": r.get("notice_type"), "form_type": r.get("form_type"),
        "published": r.get("published") or None,
        "deadline": (r.get("deadline") or None) or None,
        "deadline_is_proxy": bool(r.get("deadline_is_proxy")),
        "value_eur": r.get("value_eur"),
        "score": r["score"], "tier": r["tier"], "why_matched": r.get("why"),
        "found_by": r.get("found_by", "cpv"),
        "disqualified": dq, "disqualification_reason": why,
        "batch_date": batch,
        "document_url": r.get("document_url"),
        "document_language": r.get("document_language") or [],
        "document_restricted": r.get("document_restricted"),
        "submission_language": r.get("submission_language") or [],
        "submission_url": r.get("submission_url"),
        "electronic_submission": r.get("electronic_submission"),
        "deadline_time": r.get("deadline_time"),
        "questions_deadline": r.get("questions_deadline"),
        "contact_email": r.get("contact_email"),
        "validity_value": int(r["validity_value"]) if str(r.get("validity_value") or "").isdigit() else None,
        "validity_unit": r.get("validity_unit"),
    }

def known_ids(rows):
    """Which of these notices are already in the DB. State lives in Supabase,
    not in a file or in git - so the Action never writes back to the repo."""
    if not rows: return set()
    ids = ",".join(f'"{r["notice_id"]}"' for r in rows)
    got = rest("GET", f"rfps?select=source,notice_id&notice_id=in.({ids})")
    return {(g["source"], g["notice_id"]) for g in got}

def main(path):
    rows_in = json.load(open(path))
    batch = datetime.date.today().isoformat()
    rows = [to_row(r, batch) for r in rows_in]
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    seen = known_ids(rows)
    fresh = [r for r in rows if (r["source"], r["notice_id"]) not in seen]
    saved = []
    if rows:
        # upsert on (source, notice_id) - running twice never duplicates
        rest("POST", "rfps?on_conflict=source,notice_id", rows,
             prefer="resolution=merge-duplicates,return=minimal")
        # only the NEW ones go to Slack
        if fresh:
            ids = ",".join(f'"{r["notice_id"]}"' for r in fresh)
            saved = rest("GET", f"rfps?select=*&notice_id=in.({ids})")
    dq = sum(1 for r in rows if r["disqualified"])

    # Funnel stats go to the DB, not a file: the Slack digest is rendered by a
    # Claude routine on a different machine, which never sees the runner's disk.
    stats_path = ROOT / "data" / f"stats_{batch}.json"
    stats = json.load(open(stats_path)) if stats_path.exists() else {}
    rest("POST", "rfp_batches?on_conflict=batch_date", [{
        "batch_date": batch,
        "days": stats.get("days"), "scanned": stats.get("scanned", 0),
        "scanned_de": stats.get("scanned_de", 0), "scanned_ted": stats.get("scanned_ted", 0),
        "by_cpv": stats.get("by_cpv", 0), "by_fulltext": stats.get("by_fulltext", 0),
        "qualified": len(rows), "new_rows": len(fresh), "disqualified": dq,
    }], prefer="resolution=merge-duplicates,return=minimal")
    rest("POST", "automation_runs", [{
        "project": "rfp-radar", "task": "daily-scan",
        "started_at": started,
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "success", "rows_affected": len(fresh),
        "notes": (f"{len(rows)} qualified ({len(fresh)} new) · "
                  f"{dq} disqualified by the technical screen · sources: DE Datenservice + TED/EU"),
    }], prefer="return=minimal")
    print(f"[supabase] {len(rows)} upserted, {len(fresh)} new, {dq} disqualified")
    json.dump(saved, open(ROOT / "data" / f"saved_{batch}.json", "w"),
              ensure_ascii=False, indent=1)
    return saved

if __name__ == "__main__":
    main(sys.argv[1])
