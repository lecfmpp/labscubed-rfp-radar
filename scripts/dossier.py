#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RFP dossier: pulls the full record, locates the documents, builds the
timeline and writes a briefing plus a ready-made prompt for Claude to analyse.
   python3 scripts/dossier.py <notice-id>        # 25763636 (DE) or 588408-2026 (TED)
"""
import io, json, os, re, sys, zipfile, datetime, urllib.request, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = {"User-Agent": "LabsCubed-RFP-Radar/1.0 (leandro@labscubed.com)"}
TED_API = "https://api.ted.europa.eu/v3/notices/search"

def get(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()

# ---------- source: TED ----------------------------------------------------
def from_ted(pub):
    body = json.dumps({"query": f'publication-number={pub}', "limit": 1, "fields": [
        "publication-number", "notice-title", "description-lot", "buyer-name",
        "buyer-country", "publication-date", "deadline-receipt-tender-date-lot",
        "deadline-receipt-request-date-lot", "classification-cpv", "notice-type",
        "procedure-type", "total-value", "estimated-value-lot", "links",
        "place-of-performance-country-lot"]}).encode()
    req = urllib.request.Request(TED_API, data=body,
                                 headers={**UA, "Content-Type": "application/json"})
    import time
    for attempt in range(5):                       # TED returns 429 under load
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r); break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4: raise
            time.sleep(2 ** attempt)
    n = (d.get("notices") or [None])[0]
    if not n: raise SystemExit(f"TED: notice {pub} not found")
    def flat(v):
        if v is None: return ""
        if isinstance(v, str): return v
        if isinstance(v, list): return " ".join(flat(x) for x in v)
        if isinstance(v, dict):
            return " ".join(flat(v.get(k)) for k in ("eng", "deu") if v.get(k)) or \
                   " ".join(flat(x) for x in v.values())
        return str(v)
    return {"id": pub, "source": "EU/TED",
            "title": flat(n.get("notice-title")), "buyer": flat(n.get("buyer-name")),
            "desc": flat(n.get("description-lot")),
            "published": flat(n.get("publication-date"))[:10],
            "deadline": flat(n.get("deadline-receipt-tender-date-lot"))[:10]
                        or flat(n.get("deadline-receipt-request-date-lot"))[:10],
            "cpv": sorted(set(n.get("classification-cpv") or [])),
            "procedure": flat(n.get("procedure-type")),
            "country": flat(n.get("place-of-performance-country-lot")),
            "value": flat(n.get("estimated-value-lot")) or flat(n.get("total-value")),
            "url": f"https://ted.europa.eu/en/notice/-/detail/{pub}",
            # NOTE: TED's /xml and /pdf are asynchronous (HTTP 202, empty body on the
            # first call). The detail page is the reliable route; it carries the link
            # to the buyer's own procurement portal.
            "docs": [f"https://ted.europa.eu/en/notice/-/detail/{pub}"]}

# ---------- source: Germany (eForms XML inside the daily export) -----------
NS = re.compile(r"^\{[^}]*\}")
def txt(el): return (el.text or "").strip() if el is not None else ""

def from_de(nid, day=None):
    import xml.etree.ElementTree as ET
    days = [day] if day else [(datetime.date.today() - datetime.timedelta(days=i)).isoformat()
                              for i in range(0, 45)]
    for d in days:
        try:
            z = zipfile.ZipFile(io.BytesIO(get(
                f"https://oeffentlichevergabe.de/api/notice-exports?pubDay={d}&format=eforms.zip")))
        except Exception:
            continue
        hit = [n for n in z.namelist() if n.startswith(str(nid))]
        if not hit: continue
        root = ET.fromstring(z.read(hit[0]).decode("utf-8"))
        def find(tag):
            return [e for e in root.iter() if NS.sub("", e.tag) == tag]
        docs = [txt(e) for e in find("URI") if txt(e).startswith("http")]
        dl = ""
        for t in ("EndDate", "ReceiptDate", "SubmissionDueDate"):
            v = [txt(e) for e in find(t) if txt(e)]
            if v: dl = v[0][:10]; break
        # First <Name> = ContractingParty (the buyer); the <Name> inside
        # ProcurementProject = the contract subject. Do not confuse the two.
        names = [txt(e) for e in find("Name") if txt(e)]
        proj = [txt(e) for e in find("Name")
                if e in [c for pp in find("ProcurementProject") for c in pp.iter()]]
        return {"id": nid, "source": "DE/oeffentlichevergabe",
                "title": (proj[0] if proj else (names[1] if len(names) > 1 else names[0] if names else "")),
                "buyer": names[0] if names else "",
                "desc": " ".join(txt(e) for e in find("Description"))[:6000],
                "published": txt(next(iter(find("IssueDate")), None))[:10],
                "deadline": dl,
                "cpv": sorted({txt(e) for e in find("ItemClassificationCode") if txt(e)}),
                "procedure": txt(next(iter(find("NoticeTypeCode")), None)),
                "country": txt(next(iter(find("IdentificationCode")), None)),
                "value": txt(next(iter(find("EstimatedOverallContractAmount")), None)),
                "url": f"https://oeffentlichevergabe.de/ui/de/search/details/{nid}/01",
                "docs": sorted(set(docs)), "pubday": d}
    raise SystemExit(f"DE: notice {nid} not found in the last 45 days of exports")

# ---------- timeline -------------------------------------------------------
def timeline(rec):
    today = datetime.date.today()
    if not rec.get("deadline"):
        return ["**Deadline not published in the structured record** - confirm it on the "
                "notice page BEFORE planning. Everything below depends on it."], None
    dl = datetime.date.fromisoformat(rec["deadline"][:10])
    left = (dl - today).days
    # milestones counted backwards from the deadline
    marks = [(dl - datetime.timedelta(days=n), lbl) for n, lbl in [
        (0,  "DEADLINE - submit on the portal (submit 24h early; uploads fail)"),
        (2,  "Final review: signatures, attachments, format, compliance"),
        (7,  "Technical + commercial proposal closed internally"),
        (14, "Last working day for QUESTIONS to the buyer (check the real cut-off in the notice)"),
        (18, "Bid / no-bid decision + assemble references and certificates"),
        (21, "Technical analysis: requirement matrix vs CubeTen/CubeOne/CubeFlex"),
    ]]
    lines = [f"**Deadline: {dl.isoformat()} - {left} days left**", ""]
    for d, lbl in sorted(marks):
        flag = "[done]" if d < today else ("**TODAY**" if d == today else "")
        lines.append(f"- `{d.isoformat()}` {lbl} {flag}")
    if left < 21:
        lines += ["", f"> **Tight window ({left} days).** The milestones above are compressed - "
                      "decide bid/no-bid within 48 hours."]
    return lines, left

# ---------- report ---------------------------------------------------------
def report(rec):
    tl, left = timeline(rec)
    docs = rec.get("docs") or []
    md = [f"# RFP Dossier - {rec['title'][:120]}", "",
          "| | |", "|---|---|",
          f"| **ID** | `{rec['id']}` ({rec['source']}) |",
          f"| **Buyer** | {rec['buyer'] or '-'} |",
          f"| **Country** | {rec.get('country') or '-'} |",
          f"| **Published** | {rec.get('published') or '-'} |",
          f"| **Deadline** | {rec.get('deadline') or '**not published - confirm**'} |",
          f"| **CPV** | {', '.join(rec['cpv']) or '-'} |",
          f"| **Procedure** | {rec.get('procedure') or '-'} |",
          f"| **Estimated value** | {rec.get('value') or '-'} |",
          f"| **Notice** | {rec['url']} |", "",
          "## Subject", "", (rec.get("desc") or "-")[:2500], "",
          "## Timeline", ""] + tl + ["", "## Tender documents", ""]
    md += [f"- {u}" for u in docs] or \
          ["- No direct link in the structured record. Open the notice page and download "
           "manually (many portals require registration / activating participation)."]
    md += ["", "## Next steps", "",
        "1. **Confirm the real deadline** on the notice page (the structured record does not always carry it).",
        "2. **Bid / no-bid** - use the technical screen below.",
        "3. If BID: register on the buyer's portal and activate participation "
        "(in Germany, 'Teilnahme aktivieren' - only then do you receive amendments to the notice).",
        "4. Download every attachment and run the Claude analysis (prompt at the end of this file).",
        "5. Submit questions to the buyer within the cut-off - it is the only lever to influence "
        "specifications written around a competitor.", "",
        "## LabsCubed technical screen", "",
        "| Criterion | Limit | Check in the notice |",
        "|---|---|---|",
        "| Max force | CubeTen 10 kN · CubeOne 1 kN | request >10 kN = **no-bid** |",
        "| Material | rigid plastics, rubbers, elastomers | metal/concrete = **no-bid** |",
        "| Test type | tensile, flexure, tear | hardness, impact/Charpy, fatigue = **no-bid** |",
        "| Standards | ASTM D638/D412/D624/D790 · ISO 527/37/178 | others = assess |",
        "| Elongation | up to 1000% | above = **no-bid** |",
        "| Automation | up to 15 specimens per run | larger request = assess |",
        "| Footprint | 0.8 x 1.2 m · 113 kg | check the lab's constraints |",
        "| Software | cloud Portal + AI Suite; SAP/Uncountable/Alpha Workbench | "
        "on-premise requirement = risk |", "",
        "## Prompt for the Claude analysis", "", "```",
        f"Analyse the RFP documents in {ROOT}/dossiers/{rec['id']}/ for LabsCubed",
        "(CubeTen: tensile, rigid plastics, 10kN, ASTM D638/ISO 527; CubeOne: tensile/tear,",
        "rubbers, 1kN, ASTM D412/ISO 37/D624; CubeFlex: flexure, ASTM D790/ISO 178;",
        "cloud Portal + AI Suite). Produce:",
        "1. Bid/no-bid verdict with reasoning, using the technical screen in this dossier.",
        "2. Requirement-by-requirement matrix: requirement | does CubeTen/One/Flex meet it? |",
        "   evidence | gap.",
        "3. Technical gaps and how to address each (partner, option, declared exception).",
        "4. Award criteria and their weights; where we win points and where we lose them.",
        "5. Eligibility requirements (references, certificates, turnover, insurance) and",
        "   which of them we do not meet today.",
        "6. Questions to submit to the buyer (ambiguous specs, or specs written around",
        "   a competitor).",
        "7. Section-by-section proposal structure, with who answers what and in how many days.",
        "",
        "Mark anything you cannot evidence from the documents as [GAP] or [NEEDS HUMAN].",
        "Never assert compliance that the documents do not support.",
        "```", ""]
    return "\n".join(md)

if __name__ == "__main__":
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    ident = sys.argv[1]
    rec = from_ted(ident) if re.fullmatch(r"\d+-\d{4}", ident) else from_de(ident)
    outdir = ROOT / "dossiers" / str(rec["id"]); outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "dossier.md").write_text(report(rec), encoding="utf-8")
    json.dump(rec, open(outdir / "notice.json", "w"), ensure_ascii=False, indent=1)
    for i, u in enumerate(rec.get("docs") or []):
        try:
            b = get(u, timeout=90)
            if not b:                       # 202 assincrono / vazio: nao gravar lixo
                print(f"  empty (async), open in a browser: {u}", file=sys.stderr); continue
            ext = ".pdf" if b[:4] == b"%PDF" else ".html"
            (outdir / f"doc{i}{ext}").write_bytes(b)
            print(f"  downloaded: doc{i}{ext} ({len(b)} bytes) <- {u}", file=sys.stderr)
        except Exception as e:
            print(f"  FAILED to download {u}: {e}", file=sys.stderr)
    print(report(rec))
    print(f"\n--> {outdir}/dossier.md", file=sys.stderr)
