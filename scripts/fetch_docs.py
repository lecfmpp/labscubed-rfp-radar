#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download the tender documents for one RFP and record what happened.

   python3 scripts/fetch_docs.py <rfp-id-or-notice-id>

Portals differ. Three outcomes, all recorded honestly in rfps.docs_fetch_note:
  downloaded  - files retrieved, listed in rfp_documents
  gated       - the portal requires a free account; a human registers once
  none        - the notice published no document URL at all

IMPORTANT: an anonymous download usually means you are NOT subscribed to
amendments. A corrigendum can move the deadline or change the specification, so
for any tender you intend to bid on, register on the portal and activate
participation - do not rely on the anonymous copy.
"""
import json, os, re, sys, urllib.parse, urllib.request, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL  = os.environ["SUPABASE_URL"].rstrip("/")
KEY  = os.environ["SUPABASE_SERVICE_KEY"]
UA   = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}

def rest(method, path, payload=None, prefer=None):
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
         "Content-Type": "application/json"}
    if prefer: h["Prefer"] = prefer
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
        return json.loads(b) if b else []

# --- portal adapters -------------------------------------------------------

def etenders_ie(doc_url, opener):
    """etenders.gov.ie: two hops per file - an interstitial that offers
    'proceed without association', then the actual download."""
    rid = urllib.parse.parse_qs(urllib.parse.urlparse(doc_url).query).get("resourceId", [None])[0]
    if not rid: return []
    base = "https://www.etenders.gov.ie/epps/cft"
    listing = opener.open(urllib.request.Request(doc_url, headers=UA), timeout=60).read().decode("utf-8", "ignore")
    ids = re.findall(r"downloadDocForAnonymous\('(\d+)'\)", listing)
    out = []
    for did in ids:
        try:
            opener.open(urllib.request.Request(
                f"{base}/prepareAnonymousDownload.do?resourceId={rid}&documentId={did}",
                headers={**UA, "Referer": doc_url}), timeout=60).read()
            r = opener.open(urllib.request.Request(
                f"{base}/downloadContractDocument.do?documentId={did}&resourceId={rid}",
                headers={**UA, "Referer": f"{base}/prepareAnonymousDownload.do?resourceId={rid}&documentId={did}"}),
                timeout=120)
            cd = r.headers.get("Content-Disposition", "")
            name = (re.search(r'filename="([^"]+)"', cd) or [None, f"doc-{did}"])[1]
            out.append((name, r.read(), r.headers.get("Content-Type", "")))
        except Exception as e:
            print(f"  {did}: {e}", file=sys.stderr)
    return out

GATED = ("deutsche-evergabe.de", "evergabe-online.de", "dtvp.de", "vergabe.")

def fetch(doc_url):
    """Returns (files, note). files = [(name, bytes, mime)]"""
    if not doc_url:
        return [], "none - the notice published no document URL; request them by email"
    cj = urllib.request.HTTPCookieProcessor()
    opener = urllib.request.build_opener(cj)
    host = urllib.parse.urlparse(doc_url).netloc
    if "etenders.gov.ie" in host:
        files = etenders_ie(doc_url, opener)
        if files:
            return files, (f"downloaded {len(files)} file(s) anonymously from {host} - "
                           "NOT subscribed to amendments; register before bidding")
        return [], f"gated - {host} released nothing anonymously"
    if any(g in host for g in GATED):
        return [], (f"gated - {host} requires a free account to release the documents. "
                    "Register once, then activate participation so amendments arrive.")
    # Generic: try a direct fetch and keep it only if it is a real file.
    try:
        r = opener.open(urllib.request.Request(doc_url, headers=UA), timeout=90)
        b, ct = r.read(), r.headers.get("Content-Type", "")
        if b[:4] == b"%PDF" or b[:2] == b"PK" or "application" in ct:
            cd = r.headers.get("Content-Disposition", "")
            name = (re.search(r'filename="([^"]+)"', cd) or [None, "document"])[1]
            return [(name, b, ct)], f"downloaded 1 file from {host}"
        return [], f"gated - {host} returned a web page, not a document; open it manually"
    except Exception as e:
        return [], f"failed - {host}: {e}"


def main(ident):
    key = "id" if re.fullmatch(r"[0-9a-f-]{36}", ident) else "notice_id"
    rows = rest("GET", f"rfps?{key}=eq.{ident}&select=*")
    if not rows: raise SystemExit(f"RFP {ident} not found")
    r = rows[0]
    print(f"{r['title'][:90]}\n  buyer: {r.get('buyer')}")
    print(f"  documents in : {', '.join(r.get('document_language') or []) or '?'}")
    print(f"  SUBMIT IN    : {', '.join(r.get('submission_language') or []) or '?'}")
    print(f"  deadline     : {r.get('deadline')} {r.get('deadline_time') or ''}")
    print(f"  questions by : {r.get('questions_deadline') or 'not published'}")
    print(f"  ask          : {r.get('contact_email') or 'not published'}")

    files, note = fetch(r.get("document_url"))
    outdir = ROOT / "dossiers" / str(r["id"]); outdir.mkdir(parents=True, exist_ok=True)
    saved = []
    for name, blob, mime in files:
        safe = re.sub(r"[^\w.\- ]", "_", name)[:120]
        (outdir / safe).write_bytes(blob)
        saved.append({"rfp_id": r["id"], "filename": safe, "url": r.get("document_url"),
                      "mime": mime, "bytes": len(blob)})
        print(f"  saved: {safe} ({len(blob):,} bytes)")
    if saved:
        rest("POST", "rfp_documents", saved, prefer="return=minimal")
    rest("PATCH", f"rfps?id=eq.{r['id']}",
         {"docs_fetched": bool(saved), "docs_fetch_note": note},
         prefer="return=minimal")
    print(f"  -> {note}")


if __name__ == "__main__":
    main(sys.argv[1])
