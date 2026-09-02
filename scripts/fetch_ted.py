# -*- coding: utf-8 -*-
"""Source 2 - the whole EU: TED (Tenders Electronic Daily), api.ted.europa.eu.
Public API, POST /v3/notices/search, NO authentication.
Covers the 27 member states above the European thresholds.
"""
import json, sys, os, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from score import score_notice
from criteria import CPV_CORE, CPV_BROAD

API = "https://api.ted.europa.eu/v3/notices/search"
FIELDS = ["publication-number", "notice-title", "buyer-name", "publication-date",
          "deadline-receipt-tender-date-lot", "classification-cpv",
          "place-of-performance-country-lot", "notice-type",
          "total-value", "links", "description-lot",
          # Everything needed to actually bid: where the documents are, what
          # language the PROPOSAL must be in, when questions close, who to ask.
          "document-url-lot", "document-official-language-lot",
          "document-restricted-lot", "submission-language", "submission-url-lot",
          "electronic-submission-lot", "deadline-receipt-tender-time-lot",
          "deadline-receipt-answers-date-lot", "organisation-email-addinfo-lot",
          "tender-validity-deadline-value-lot", "tender-validity-deadline-unit-lot"]

def q(days=7):
    cpvs = " ".join(sorted(CPV_CORE | (CPV_BROAD - {"48000000", "73000000", "42000000"})))
    # notice-type: calls for competition only (cn-*), not award notices
    return (f"classification-cpv IN ({cpvs}) "
            f"AND publication-date >= today(-{days}) "
            f"AND notice-type IN (cn-standard cn-social)")

def call(query, page=1, limit=100):
    body = json.dumps({"query": query, "page": page, "limit": limit,
                       "fields": FIELDS}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json",
        "User-Agent": "LabsCubed-RFP-Radar/1.0 (leandro@labscubed.com)"})
    import time
    for attempt in range(5):                       # TED returns 429 under load
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4: raise
            time.sleep(2 ** attempt)

FT_TERMS = ["universal testing machine", "tensile testing machine", "tensile test",
            "materials testing machine", "Zugprüfmaschine", "Universalprüfmaschine",
            "Materialprüfmaschine", "Werkstoffprüfmaschine", "flexural testing",
            "tear strength", "machine d'essai de traction", "ensayo de tracción"]

def q_fulltext(days=7):
    """Second pass: catches what the CPV filter misses (mis-assigned CPV).
    NOTE: TED's FT~ searches the TITLE (translated to EN), not the description."""
    terms = " OR ".join(f'FT~("{t}")' for t in FT_TERMS)
    return f"({terms}) AND publication-date >= today(-{days})"

def first(v):
    """TED returns most lot-scoped fields as a list, one entry per lot."""
    if isinstance(v, list): return v[0] if v else None
    return v or None

def flat(v):
    """TED returns multilingual dicts {'eng':[...], 'deu':[...]}."""
    if v is None: return ""
    if isinstance(v, str): return v
    if isinstance(v, list): return " ".join(flat(x) for x in v)
    if isinstance(v, dict): return " ".join(flat(x) for x in v.values())
    return str(v)

def run(days=7, countries=None):
    out, seen, total = [], set(), 0
    for query, label in ((q(days), "cpv"), (q_fulltext(days), "fulltext")):
      page = 1
      while True:
        d = call(query, page=page)
        total += d.get("totalNoticeCount", 0) if label == "cpv" else 0
        batch = d.get("notices", [])
        if not batch: break
        for n in batch:
            if n.get("publication-number") in seen: continue
            seen.add(n.get("publication-number"))
            tt = n.get("notice-title") or {}
            _t = tt.get("eng") or tt.get("deu") or (list(tt.values())[0] if tt else "")
            title_disp = " ".join(_t) if isinstance(_t, list) else str(_t)
            title = flat(n.get("notice-title"))
            desc  = flat(n.get("description-lot"))
            pts, tier, why = score_notice(title, desc, n.get("classification-cpv") or [])
            if label == "fulltext" and tier == "COLD":
                pts, tier, why = max(pts, 45), "WARM", (why + "; found by full-text search").strip("; ")
            if tier == "COLD": continue
            ctry = sorted(set(n.get("place-of-performance-country-lot") or []))
            if countries and not (set(ctry) & set(countries)): continue
            pub = n.get("publication-number")
            out.append({
                "source": "EU/TED", "id": pub, "score": pts, "tier": tier, "why": why,
                "title": title_disp[:400], "found_by": label, "buyer": flat(n.get("buyer-name"))[:200],
                "published": flat(n.get("publication-date"))[:10],
                "deadline": flat(n.get("deadline-receipt-tender-date-lot"))[:10],
                "country": ctry, "cpv": sorted(set(n.get("classification-cpv") or [])),
                "url": f"https://ted.europa.eu/en/notice/-/detail/{pub}",
                "xml": f"https://ted.europa.eu/en/notice/{pub}/xml",
                "document_url": first(n.get("document-url-lot")),
                "document_language": n.get("document-official-language-lot") or [],
                "document_restricted": first(n.get("document-restricted-lot")),
                "submission_language": n.get("submission-language") or [],
                "submission_url": first(n.get("submission-url-lot")),
                "electronic_submission": first(n.get("electronic-submission-lot")),
                "deadline_time": first(n.get("deadline-receipt-tender-time-lot")),
                "questions_deadline": (first(n.get("deadline-receipt-answers-date-lot")) or "")[:10] or None,
                "contact_email": first(n.get("organisation-email-addinfo-lot")),
                "validity_value": first(n.get("tender-validity-deadline-value-lot")),
                "validity_unit": first(n.get("tender-validity-deadline-unit-lot")),
            })
        if len(batch) < 100: break
        page += 1
    out.sort(key=lambda r: -r["score"])
    return out, total

if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    res, total = run(days)
    print(f"[TED] last {days}d: {total} notices in target CPVs -> {len(res)} qualified "
          f"(HOT={sum(1 for r in res if r['tier']=='HOT')}, "
          f"WARM={sum(1 for r in res if r['tier']=='WARM')})")
    json.dump(res, open(f"data/ted_{days}d.json", "w"), ensure_ascii=False, indent=1)
    for r in res[:20]:
        print(f"  {r['score']:3d} {r['tier']:4} {','.join(r['country'])[:7]:7} | {r['title'][:70]}")
        print(f"      {r['buyer'][:60]} | deadline {r['deadline']} | {r['why'][:95]}")
