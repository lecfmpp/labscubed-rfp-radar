# -*- coding: utf-8 -*-
"""Source 1 - Germany: Datenservice Oeffentlicher Einkauf (oeffentlichevergabe.de).
Official Open Data interface, no authentication. Daily/monthly ZIP of CSVs.
GET /api/notice-exports?pubDay=YYYY-MM-DD&format=csv.zip   (or pubMonth=YYYY-MM)
"""
import csv, io, sys, os, zipfile, urllib.request, json
sys.path.insert(0, os.path.dirname(__file__))
from score import score_notice

BASE = "https://oeffentlichevergabe.de/api/notice-exports"
UA = {"User-Agent": "LabsCubed-RFP-Radar/1.0 (leandro@labscubed.com)"}

def fetch(period):
    key = "pubMonth" if len(period) == 7 else "pubDay"
    url = f"{BASE}?{key}={period}&format=csv.zip"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        return zipfile.ZipFile(io.BytesIO(r.read()))

def rows(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, "utf-8"))

def run(period):
    z = fetch(period)
    notices = {r["noticeIdentifier"]: r for r in rows(z, "notice.csv")}

    cpv, texts = {}, {}
    for r in rows(z, "classification.csv"):
        if r["classificationType"] != "cpv": continue
        s = cpv.setdefault(r["noticeIdentifier"], set())
        s.add(r["mainClassificationCode"])
        s.update(c for c in (r["additionalClassificationCodes"] or "").split() if c)

    val = {}
    for r in rows(z, "purpose.csv"):
        n = r["noticeIdentifier"]
        t = texts.setdefault(n, {"title": set(), "desc": set()})
        if r["title"]: t["title"].add(r["title"])
        if r["description"]: t["desc"].add(r["description"])
        if r.get("estimatedValue"):
            try: val[n] = max(val.get(n, 0), float(r["estimatedValue"]))
            except ValueError: pass

    buyer, city = {}, {}
    for r in rows(z, "organisation.csv"):          # first org = contracting authority
        n = r["noticeIdentifier"]
        buyer.setdefault(n, r.get("organisationName") or "")
        city.setdefault(n, f'{r.get("organisationCity","")} / {r.get("organisationCountryCode","")}')

    # NOTE: the DOE CSV export does not carry the tender submission deadline (BT-131).
    # publicOpeningDate is the best available proxy; the exact deadline is pulled
    # from the eForms XML / detail page by dossier.py.
    deadline = {}
    for r in rows(z, "submissionTerms.csv"):
        if r.get("publicOpeningDate"):
            deadline.setdefault(r["noticeIdentifier"], r["publicOpeningDate"][:10])

    # OPEN opportunities only: competition and planning (prior information).
    # Excludes result/can-* (already awarded) and cont-modif (contract change).
    OPEN = {"competition", "change", "planning"}
    out = []
    for nid, n in notices.items():
        if n.get("formType") not in OPEN: continue
        t = texts.get(nid, {"title": set(), "desc": set()})
        title = " | ".join(sorted(t["title"]))[:400]
        desc = " ".join(sorted(t["desc"]))[:4000]
        pts, tier, why = score_notice(title, desc, cpv.get(nid, ()))
        if tier == "COLD": continue
        out.append({
            "source": "DE/oeffentlichevergabe",
            "id": nid, "score": pts, "tier": tier, "why": why,
            "title": title, "buyer": buyer.get(nid, ""), "city": city.get(nid, ""),
            "published": n.get("publicationDate", "")[:10],
            "deadline": deadline.get(nid, ""), "deadline_is_proxy": True,
            "value_eur": val.get(nid),
            "cpv": sorted(cpv.get(nid, ())),
            "url": f"https://oeffentlichevergabe.de/ui/de/search/details/{nid}/01",
            "notice_type": n.get("noticeType", ""), "form_type": n.get("formType", ""),
            "procedure": n.get("procedureIdentifier", ""),
        })
    out.sort(key=lambda r: -r["score"])
    seen, dedup = set(), []
    for r in out:                      # one row per procedure (versions/lots repeat)
        k = r["procedure"] or r["id"]
        if k in seen: continue
        seen.add(k); dedup.append(r)
    return dedup, len(notices)

if __name__ == "__main__":
    period = sys.argv[1]
    res, total = run(period)
    print(f"[DE] {period}: {total} notices scanned -> {len(res)} qualified "
          f"(HOT={sum(1 for r in res if r['tier']=='HOT')}, "
          f"WARM={sum(1 for r in res if r['tier']=='WARM')})")
    json.dump(res, open(f"data/de_{period}.json", "w"), ensure_ascii=False, indent=1)
    for r in res[:15]:
        print(f"  {r['score']:3d} {r['tier']:4} | {r['title'][:78]}")
        print(f"      {r['buyer'][:70]} | {r['why'][:110]}")
