#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic, free enrichment of WARM/HOT tenders — no model, no paid tools.

For each qualifying tender in a batch this:
  1. pulls the full structured notice from the source's free API
     (TED API v3, or oeffentlichevergabe.de /api/notices/<id> eForms XML),
  2. builds a requirement_matrix by screening the notice text against the
     LabsCubed envelope (force, material, test type, standards, elongation) and
     records eligibility asks (turnover, ISO 9001, references, insurance) as
     [NEEDS HUMAN] — never asserting compliance the text doesn't support,
  3. derives a bid/no-bid verdict from the hard technical gates,
  4. writes a structured timeline off the deadline,
  5. best-effort downloads the tender documents via fetch_docs (honest about
     portals that gate behind a free account), and
  6. patches it all back into `rfps` (+ rfp_documents).

Everything here is Python stdlib only, so it runs inside the existing Action
with no extra dependency and no workflow change. Called at the end of
push_supabase.py; also runnable alone:
   python3 scripts/enrich.py <notice-id>      # one tender, dry-run print
   python3 scripts/enrich.py --batch 2026-09-03 [--limit 12] [--write]
"""
import os, re, sys, json, datetime, urllib.request, urllib.error, urllib.parse, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import dossier                                   # from_ted() — free TED API v3
try:
    import fetch_docs                            # portal-aware document downloader
except Exception:
    fetch_docs = None

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
UA  = {"User-Agent": "LabsCubed-RFP-Radar/1.0 (leandro@labscubed.com)"}


STORAGE_BUCKET = "portal-assets"   # same private bucket the portal Files page uses


def storage_upload(rfp_id, name, blob, mime):
    """Upload a downloaded document into Storage; the portal signs a URL to
    preview it. Path: rfp/<rfp_id>/<safe-name>. Returns the storage path."""
    safe = re.sub(r"[^\w.\-]", "_", name)[:120] or "document"
    path = f"rfp/{rfp_id}/{safe}"
    endpoint = f"{URL}/storage/v1/object/{STORAGE_BUCKET}/{urllib.parse.quote(path)}"
    req = urllib.request.Request(endpoint, data=blob, method="POST",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                 "Content-Type": mime or "application/octet-stream", "x-upsert": "true"})
    urllib.request.urlopen(req, timeout=180).read()
    return path


def rest(method, path, payload=None, prefer=None):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
        return json.loads(b) if b else []


# --------------------------------------------------------------------------
# Free structured record for a German notice (single-notice eForms XML).
# dossier.from_de reads the whole daily export ZIP (heavy, IP-blocked); the
# per-notice endpoint is cheap and reliable, so enrichment uses this instead.
# --------------------------------------------------------------------------
def from_de_single(nid):
    import xml.etree.ElementTree as ET
    raw = urllib.request.urlopen(
        urllib.request.Request(f"https://oeffentlichevergabe.de/api/notices/{nid}", headers=UA),
        timeout=60).read().decode("utf-8", "ignore")
    root = ET.fromstring(raw)
    strip = lambda t: re.sub(r"^\{[^}]*\}", "", t)
    def find(tag):
        return [e for e in root.iter() if strip(e.tag) == tag]
    def txt(el):
        return (el.text or "").strip() if el is not None else ""
    names = [txt(e) for e in find("Name") if txt(e)]
    descs = [txt(e) for e in find("Description") if txt(e)]
    # the subject description is the longest one that isn't the boilerplate
    # review-board paragraph; buyer is the first ContractingParty <Name>.
    subj = max((d for d in descs), key=len, default="")
    dl, dlt = "", ""
    for t in ("EndDate",):
        v = [txt(e)[:10] for e in find(t) if txt(e)]
        if v:
            dl = v[0]; break
    v = [txt(e)[:8] for e in find("EndTime") if txt(e)]
    if v:
        dlt = v[0]
    docs = sorted({txt(e) for e in find("URI") if txt(e).startswith("http")})
    emails = sorted({txt(e) for e in find("ElectronicMail") if "@" in txt(e)})
    return {
        "id": nid, "source": "DE/oeffentlichevergabe",
        "title": (descs[1] if len(descs) > 1 else (names[1] if len(names) > 1 else "")),
        "buyer": names[0] if names else "", "desc": subj[:6000],
        "deadline": dl, "deadline_time": dlt,
        "cpv": sorted({txt(e) for e in find("ItemClassificationCode") if txt(e)}),
        "country": "DEU", "value": txt(next(iter(find("EstimatedOverallContractAmount")), None)),
        "url": f"https://oeffentlichevergabe.de/ui/de/search/details/{nid}/01",
        "contact_email": emails[0] if emails else None, "docs": docs,
    }


SAM_UA = {"User-Agent": UA["User-Agent"], "Accept": "application/json, text/plain, */*"}


def _sam_json(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=SAM_UA), timeout=60).read())


def from_sam(nid):
    """Free structured record for a SAM.gov opportunity (keyless detail API)."""
    d = _sam_json(f"https://sam.gov/api/prod/opps/v2/opportunities/{nid}")
    d2 = d.get("data2") or {}
    dd = d.get("description")
    body = str((dd[0] if isinstance(dd, list) and dd else {}).get("body") or "")
    desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
    deadline = (((d2.get("solicitation") or {}).get("deadlines") or {}).get("response") or "")[:10]
    poc = d2.get("pointOfContact") or []
    email = next((p.get("email") for p in poc if isinstance(p, dict) and p.get("email")), None)
    return {
        "id": nid, "source": "US/SAM", "title": d2.get("title") or "",
        "desc": desc[:6000], "buyer": None, "country": "USA",
        "deadline": deadline or None, "deadline_time": None,
        "cpv": [], "value": None, "contact_email": email,
        "url": f"https://sam.gov/opp/{nid}/view",
        "docs": [f"https://sam.gov/api/prod/opps/v3/opportunities/{nid}/resources"],
    }


def load_record(row):
    """Free structured record for a DB row, dispatched by source."""
    src = (row.get("source") or "")
    nid = str(row["notice_id"])
    if src.startswith("US/SAM"):
        return from_sam(nid)
    if re.fullmatch(r"\d+-\d{4}", nid):           # TED publication number
        return dossier.from_ted(nid)
    return from_de_single(nid)


def sam_attachments(nid):
    """PDF attachments for a SAM opportunity. Both the listing AND the download of
    PUBLIC files are keyless via the sam.gov SPA endpoint (api.sam.gov needs a key
    and 404s here). Access-controlled files stay behind sam.gov account access."""
    try:
        lst = _sam_json(f"https://sam.gov/api/prod/opps/v3/opportunities/{nid}/resources")
    except Exception as e:
        return [], f"could not list attachments ({e})"
    atts = []
    for grp in (lst.get("_embedded", {}).get("opportunityAttachmentList") or []):
        atts += grp.get("attachments") or []
    pdfs = [a for a in atts if a.get("fileExists") == "1" and str(a.get("mimeType") or "").lower() == ".pdf"]
    if not pdfs:
        return [], "no PDF attachments on this notice"
    controlled = sum(1 for a in pdfs if a.get("accessLevel") != "public")
    files = []
    for a in [x for x in pdfs if x.get("accessLevel") == "public"]:
        rid = a.get("resourceId")
        url = f"https://sam.gov/api/prod/opps/v3/opportunities/resources/files/{rid}/download"
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=SAM_UA), timeout=120).read()
            if b[:4] == b"%PDF":
                files.append((a.get("name") or (rid + ".pdf"), b, "application/pdf"))
        except Exception:
            pass
    note = f"downloaded {len(files)} public PDF(s)"
    if controlled:
        note += f"; {controlled} access-controlled (request access on sam.gov)"
    return files, note


# --------------------------------------------------------------------------
# The technical screen, as data. Mirrors dossier.py's LabsCubed screen and
# criteria.py's disqualifiers, but emits a structured matrix + a verdict.
# --------------------------------------------------------------------------
MAT_OK = ["plastic", "kunststoff", "polymer", "rubber", "gummi", "elastomer", "plástico", "plastik"]
MAT_NO = ["concrete", "beton", "asphalt", "cement", "zement", "steel", "stahl", "metal", "metall",
          "rebar", "bewehrung", "soil", "boden", "geotech", "gestein", "rock"]
TEST_OK = ["tensile", "zug", "traction", "tração", "flexur", "biege", "tear", "reiß", "weiterreiß", "elongation", "dehnung"]
TEST_NO = ["hardness", "härte", "durometer", "rockwell", "vickers", "brinell", "impact", "charpy",
           "kerbschlag", "izod", "fatigue", "ermüdung", "creep", "kriech"]
STANDARDS = ["astm d638", "astm d882", "astm d1708", "astm d412", "astm d624",
             "iso 527", "iso 37", "iso 34", "jis k7161", "jis k7127", "jis k6251", "jis k6252"]
STANDARDS_FLEX = ["astm d790", "iso 178", "jis k7171"]   # secondary (CubeFlex in dev)
ELIG = [("Annual turnover", ["turnover", "umsatz", "chiffre d'affaires"]),
        ("ISO 9001 / quality cert", ["iso 9001", "qualitätsmanagement", "quality management"]),
        ("Reference projects", ["reference", "referenz", "referenzen", "référence"]),
        ("Insurance", ["insurance", "versicherung", "haftpflicht"]),
        ("Bid / bank guarantee", ["bank guarantee", "bürgschaft", "bid bond", "sicherheitsleistung"])]


def mark_fit(ok, gap=None):
    return ok if not gap else gap


def build_matrix(rec):
    """Returns (matrix_rows, verdict). Rows are {requirement, notice_says, fit}."""
    text = f"{rec.get('title','')} {rec.get('desc','')}".lower()
    rows, hard_no = [], []

    # Max force ------------------------------------------------------------
    kns = [int(m) for m in re.findall(r"(\d{1,4})\s*(?:kn|kilonewton)", text)]
    if kns:
        mx = max(kns)
        if mx <= 10:
            fit = f"✓ within CubeTen (≤10 kN)"
        else:
            fit = f"[GAP] {mx} kN exceeds CubeTen's 10 kN maximum"
            hard_no.append(f"force {mx} kN > 10 kN")
        rows.append({"requirement": "Max force", "notice_says": f"{mx} kN", "fit": fit})
    else:
        rows.append({"requirement": "Max force", "notice_says": "not stated in the notice",
                     "fit": "[NEEDS HUMAN] confirm from the spec documents"})

    # Material -------------------------------------------------------------
    ok = [k for k in MAT_OK if k in text]; no = [k for k in MAT_NO if k in text]
    if no and not ok:
        rows.append({"requirement": "Material", "notice_says": ", ".join(no[:3]),
                     "fit": "[GAP] outside our envelope (plastics / rubber / elastomers only)"})
        hard_no.append(f"material: {no[0]}")
    elif ok:
        rows.append({"requirement": "Material", "notice_says": ", ".join(ok[:3]),
                     "fit": "✓ plastics / rubber / elastomers — in envelope"})
    else:
        rows.append({"requirement": "Material", "notice_says": "not stated in the notice",
                     "fit": "[NEEDS HUMAN] confirm from the spec documents"})

    # Test type — tensile/tear primary; flexure is secondary (CubeFlex in dev) --
    tensile_ok = [k for k in TEST_OK if k != "flexur" and k != "biege" and k in text]
    flex_only = (not tensile_ok) and ("flexur" in text or "biege" in text or "bending" in text)
    no = [k for k in TEST_NO if k in text]
    if no and not (tensile_ok or flex_only):
        rows.append({"requirement": "Test type", "notice_says": ", ".join(no[:3]),
                     "fit": "[GAP] unsupported test type (we do tensile / tear)"})
        hard_no.append(f"test type: {no[0]}")
    elif tensile_ok:
        rows.append({"requirement": "Test type", "notice_says": ", ".join(tensile_ok[:3]),
                     "fit": "✓ tensile / tear — supported"})
    elif flex_only:
        rows.append({"requirement": "Test type", "notice_says": "flexure / bending",
                     "fit": "[NEEDS HUMAN] flexure only — CubeFlex still in development"})
    else:
        rows.append({"requirement": "Test type", "notice_says": "not stated in the notice",
                     "fit": "[NEEDS HUMAN] confirm from the spec documents"})

    # Standards — primary (tensile/tear) vs secondary (flexure) ---------------
    hit = [s for s in STANDARDS if s in text]
    flex = [s for s in STANDARDS_FLEX if s in text]
    if hit:
        rows.append({"requirement": "Standards", "notice_says": ", ".join(s.upper() for s in hit[:4]),
                     "fit": "✓ tensile/tear standards LabsCubed builds to"})
    elif flex:
        rows.append({"requirement": "Standards", "notice_says": ", ".join(s.upper() for s in flex[:3]),
                     "fit": "[NEEDS HUMAN] flexure standard — CubeFlex still in development"})
    else:
        others = re.findall(r"\b(?:astm|iso|din|en|jis)\s?[a-z]?\d{2,4}\b", text)
        rows.append({"requirement": "Standards",
                     "notice_says": ", ".join(sorted(set(o.upper() for o in others))[:4]) or "none cited",
                     "fit": "[NEEDS HUMAN] assess any standard not in our core set" if others else "— none cited in the notice"})

    # Elongation -----------------------------------------------------------
    els = [int(m) for m in re.findall(r"(\d{3,4})\s*%", text)]
    big = [e for e in els if e > 1000]
    if big:
        rows.append({"requirement": "Elongation", "notice_says": f"{max(big)} %",
                     "fit": "[GAP] beyond the 1000% supported range"})
        hard_no.append(f"elongation {max(big)}%")

    # Deadline / logistics -------------------------------------------------
    if rec.get("deadline"):
        rows.append({"requirement": "Submission deadline",
                     "notice_says": rec["deadline"] + (f" {rec['deadline_time']}" if rec.get("deadline_time") else ""),
                     "fit": "— plan the bid timeline"})

    # Eligibility (record the ask; never claim we meet it) -----------------
    for label, kws in ELIG:
        if any(k in text for k in kws):
            rows.append({"requirement": label, "notice_says": "required by the notice",
                         "fit": "[NEEDS HUMAN] confirm LabsCubed qualifies"})

    verdict = ("No-bid — outside the technical envelope (" + "; ".join(hard_no) + ")"
               if hard_no else
               "Bid candidate — passes the technical screen; verify eligibility and the full spec documents")
    return rows, verdict


def build_timeline(rec):
    """Structured milestones the portal Timeline card renders ({date,label})."""
    tl = []
    if rec.get("published"):
        tl.append({"date": rec["published"][:10], "label": "Notice published"})
    dl = rec.get("deadline")
    if not dl:
        tl.append({"label": "Deadline not in the structured record — confirm on the notice page before planning"})
        return tl
    try:
        d = datetime.date.fromisoformat(dl[:10])
    except ValueError:
        return tl
    for off, lbl in [(21, "Technical analysis: requirement matrix vs CubeTen / CubeOne / CubeFlex"),
                     (18, "Bid / no-bid decision · assemble references + certificates"),
                     (14, "Last day for questions to the buyer (confirm the real cut-off)"),
                     (7,  "Technical + commercial proposal closed internally"),
                     (2,  "Final review: signatures, attachments, format"),
                     (0,  "DEADLINE — submit on the portal (24h early; uploads fail)")]:
        tl.append({"date": (d - datetime.timedelta(days=off)).isoformat(), "label": lbl})
    return tl


# --------------------------------------------------------------------------
def enrich_one(row, write=True):
    rec = load_record(row)
    # The scan already stored a deadline/published for the row; fall back to it
    # when the fresh structured record omits them (TED often leaves the tender
    # deadline blank in the API response).
    rec["deadline"] = rec.get("deadline") or row.get("deadline")
    rec["published"] = rec.get("published") or row.get("published")
    matrix, verdict = build_matrix(rec)
    timeline = build_timeline(rec)
    # The real documents live on the buyer's portal. Prefer the URL the scan
    # already extracted; else take the notice's own doc link — but a bare TED
    # detail page is NOT the documents, so never try to "download" from it.
    doc_url = row.get("document_url")
    if not doc_url:
        cand = next((u for u in (rec.get("docs") or []) if "ted.europa.eu" not in u), None)
        doc_url = cand

    patch = {
        "requirement_matrix": matrix,
        "timeline": timeline,
        "summary": verdict,
    }
    if doc_url and not row.get("document_url"):
        patch["document_url"] = doc_url
    if rec.get("deadline_time") and not row.get("deadline_time"):
        patch["deadline_time"] = rec["deadline_time"]
    if rec.get("contact_email") and not row.get("contact_email"):
        patch["contact_email"] = rec["contact_email"]

    is_sam = (row.get("source") or "").startswith("US/SAM")
    saved_docs, note = [], None
    if not row.get("docs_fetched") and (is_sam or (fetch_docs and doc_url)):
        try:
            files, note = sam_attachments(str(row["notice_id"])) if is_sam else fetch_docs.fetch(doc_url)
            for name, blob, mime in files:
                # Push the bytes to Storage so the portal can preview the file;
                # keep the row even if the upload fails (metadata still useful).
                sp = None
                try:
                    sp = storage_upload(row["id"], name, blob, mime)
                except Exception as e:
                    print(f"  storage upload failed ({name}): {e}", file=sys.stderr)
                saved_docs.append({"rfp_id": row["id"], "filename": re.sub(r"[^\w.\- ]", "_", name)[:120],
                                   "url": doc_url, "mime": mime, "bytes": len(blob), "storage_path": sp})
        except Exception as e:
            note = f"failed — {e}"
    if note:
        patch["docs_fetched"] = bool(saved_docs)
        patch["docs_fetch_note"] = note

    if write:
        rest("PATCH", f"rfps?id=eq.{row['id']}", patch, prefer="return=minimal")
        if saved_docs:
            rest("POST", "rfp_documents", saved_docs, prefer="return=minimal")
    return {"id": row["id"], "notice_id": row["notice_id"], "verdict": verdict,
            "rows": len(matrix), "docs": len(saved_docs), "note": note}


def enrich_batch(day=None, limit=15, write=True):
    day = day or datetime.date.today().isoformat()
    q = (f"rfps?select=id,notice_id,source,document_url,deadline,published,deadline_time,contact_email,docs_fetched"
         f"&batch_date=eq.{day}&tier=in.(HOT,WARM)&requirement_matrix=is.null"
         f"&order=score.desc&limit={limit}")
    rows = rest("GET", q)
    out = []
    for row in rows:
        try:
            out.append(enrich_one(row, write=write))
            print(f"  ✓ {row['notice_id']}: {out[-1]['verdict'][:60]} "
                  f"({out[-1]['rows']} reqs, {out[-1]['docs']} docs)", file=sys.stderr)
        except Exception as e:
            print(f"  ✗ {row['notice_id']}: {e}", file=sys.stderr)
    return out


if __name__ == "__main__":
    if "--batch" in sys.argv:
        day = sys.argv[sys.argv.index("--batch") + 1]
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 15
        res = enrich_batch(day, lim, write="--write" in sys.argv)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    elif len(sys.argv) > 1:
        # single notice, dry-run print (no --write flag needed to inspect)
        rows = rest("GET", f"rfps?select=id,notice_id,source,document_url,deadline,published,deadline_time,contact_email,docs_fetched&notice_id=eq.{sys.argv[1]}")
        if not rows:
            raise SystemExit(f"notice {sys.argv[1]} not in rfps")
        print(json.dumps(enrich_one(rows[0], write="--write" in sys.argv), indent=2, ensure_ascii=False))
    else:
        raise SystemExit(__doc__)
