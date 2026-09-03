#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""US source: SAM.gov contract opportunities (System for Award Management).

Fully public, no API key: the SPA's search + detail endpoints are keyless. We
query the Product Service Codes closest to LabsCubed's envelope (6635 Physical
Properties Testing & Inspection is the US analogue of CPV 3854) plus the strong
product keywords, then score each notice with the shared engine. Attachments
are listed here but their DOWNLOAD needs a free api.data.gov key and some are
access-controlled — enrich.py handles that separately.

   python3 scripts/fetch_sam.py [--days 3]
"""
import json, re, sys, html, datetime, urllib.request, urllib.parse, os
sys.path.insert(0, os.path.dirname(__file__))
from score import score_notice, disqualify

SEARCH = "https://sam.gov/api/prod/sgs/v1/search/"
DETAIL = "https://sam.gov/api/prod/opps/v2/opportunities/"
UA = {"User-Agent": "LabsCubed-RFP-Radar/1.0 (leandro@labscubed.com)",
      "Accept": "application/json, text/plain, */*"}

# Product Service Codes. 6635 is the direct hit; the others are adjacent lab /
# test equipment categories that only qualify when a keyword also fires.
CORE_PSC = {"6635"}                         # physical-properties testing & inspection
BROAD_PSC = {"6636", "6640", "6630", "6650"}  # environmental chambers / lab / chem-analysis / optical
# SAM full-text `q` is a loose OR match, so generic phrases return thousands of
# irrelevant hits. Precise product/brand terms stay narrow and, sorted by
# relevance, surface the real testing-machine notices a wrong PSC would hide.
TERMS = ["universal test system", "servo-hydraulic test", "tensile tester",
         "Instron", "MTS test system", "materials testing machine"]


def _get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def _search(extra, size=60, sort="-modifiedDate"):
    q = {"index": "opp", "page": "0", "size": str(size), "sort": sort,
         "mode": "search", "responseType": "json", "is_active": "true"}
    q.update(extra)
    d = _get(SEARCH + "?" + urllib.parse.urlencode(q))
    return d.get("_embedded", {}).get("results", []), d.get("page", {}).get("totalElements", 0)


def _clean(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


def _row(res, psc_bucket):
    rid = res.get("_id")
    title = res.get("title") or ""
    desc = _clean((res.get("descriptions") or [{}])[0].get("content"))
    org = (res.get("organizationHierarchy") or [{}])[-1]
    country = ((org.get("address") or {}).get("country")) or "US"
    # Give a core PSC the same weight as a core CPV by mapping it onto one, so
    # the shared scorer treats a testing-machine PSC as a strong structured hit.
    synth = ["38540000"] if psc_bucket == "core" else (["38000000"] if psc_bucket == "broad" else [])
    pts, tier, why = score_notice(title, desc, synth)
    if psc_bucket == "core" and "PSC 6635" not in why:
        why = ("PSC 6635 (physical-properties testing); " + why).strip("; ")
    dq, dqr = disqualify(title, desc)
    deadline = (res.get("responseDate") or "")[:10]
    return {
        "source": "US/SAM", "id": rid,
        "url": f"https://sam.gov/opp/{rid}/view",
        "title": title[:1000], "description": desc[:6000],
        "buyer": None, "country": country if isinstance(country, str) else "US",
        "cpv": synth, "notice_type": (res.get("type") or {}).get("value"),
        "procedure": res.get("solicitationNumber"),
        "published": (res.get("publishDate") or "")[:10],
        "deadline": deadline or None, "deadline_is_proxy": not bool(deadline),
        "value_eur": None,
        "score": pts, "tier": tier, "why": why,
        "found_by": "psc" if psc_bucket in ("core", "broad") else "fulltext",
        "disqualified": dq, "disqualification_reason": dqr,
        # the keyless resources listing; enrich.py downloads what's public.
        "document_url": f"https://sam.gov/api/prod/opps/v3/opportunities/{rid}/resources",
        "document_language": ["ENG"],
    }


def run(days=3):
    today = datetime.date.today()
    since = today - datetime.timedelta(days=days - 1)
    seen, rows, scanned = {}, [], 0

    # (field, value, bucket, sort). PSC passes are category-precise → newest
    # first; keyword passes are loose → most-relevant first.
    passes = ([("psc", p, "core", "-modifiedDate") for p in CORE_PSC]
              + [("psc", p, "broad", "-modifiedDate") for p in BROAD_PSC]
              + [("q", t, "kw", "-relevance") for t in TERMS])
    for field, val, bucket, sort in passes:
        try:
            results, total = _search({field: val}, sort=sort)
        except Exception as e:
            print(f"  SAM {field}={val}: FAILED ({e})", file=sys.stderr)
            continue
        scanned += len(results)
        for res in results:
            rid = res.get("_id")
            if not rid or rid in seen:
                continue
            pub = (res.get("publishDate") or "")[:10]
            try:
                if pub and datetime.date.fromisoformat(pub) < since:
                    continue
            except ValueError:
                pass
            row = _row(res, bucket)
            # US "physical testing" (PSC 6635) spans NDI, x-ray, balancing… far
            # wider than our tensile/flexure niche, so a PSC hit with no product
            # keyword stays COLD — surface only WARM/HOT, don't flood the table.
            if row["tier"] == "COLD":
                continue
            seen[rid] = row
            rows.append(row)
    return rows, scanned


if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 3
    rows, scanned = run(days)
    hot = [r for r in rows if r["tier"] == "HOT"]; warm = [r for r in rows if r["tier"] == "WARM"]
    print(f"SAM: scanned {scanned} -> {len(rows)} kept ({len(hot)} HOT, {len(warm)} WARM)", file=sys.stderr)
    for r in sorted(rows, key=lambda x: -x["score"])[:15]:
        print(f"  [{r['score']:>3} {r['tier']:<4}] {r['title'][:64]:64} dl={r['deadline']} {r['why'][:50]}")
