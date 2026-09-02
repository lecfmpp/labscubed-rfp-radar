#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Envia o lote do radar para o Supabase (tabela rfps) e regista em automation_runs.
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
    }

def known_ids(rows):
    """Quais destes avisos ja estao na BD. O estado vive no Supabase, nao em
    ficheiro nem no git — assim o Action nao precisa de escrever no repo."""
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
        # upsert por (source, notice_id) — correr duas vezes nao duplica
        rest("POST", "rfps?on_conflict=source,notice_id", rows,
             prefer="resolution=merge-duplicates,return=minimal")
        # so os NOVOS e que vao para o Slack
        if fresh:
            ids = ",".join(f'"{r["notice_id"]}"' for r in fresh)
            saved = rest("GET", f"rfps?select=*&notice_id=in.({ids})")
    dq = sum(1 for r in rows if r["disqualified"])
    rest("POST", "automation_runs", [{
        "project": "rfp-radar", "task": "daily-scan",
        "started_at": started,
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "success", "rows_affected": len(fresh),
        "notes": (f"{len(rows)} qualificados ({len(fresh)} novos) · "
                  f"{dq} desqualificados pelo crivo tecnico · fontes: DE Datenservice + TED/UE"),
    }], prefer="return=minimal")
    print(f"[supabase] {len(rows)} upserted, {len(fresh)} novos, {dq} desqualificados")
    json.dump(saved, open(ROOT / "data" / f"saved_{batch}.json", "w"),
              ensure_ascii=False, indent=1)
    return saved

if __name__ == "__main__":
    main(sys.argv[1])
