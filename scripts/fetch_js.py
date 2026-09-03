#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless-browser document fetcher for JavaScript-rendered public portals.

Some procurement portals (e.g. VMPSatellite / Cosinex, oeffentlichevergabe
satellites) build their document list in the browser, so the static HTML that
fetch_docs.py sees carries no links. This module drives a real headless Chromium
with Playwright to let that JS run, then downloads whatever public files the page
exposes. It CANNOT get past a login / "activate participation" wall — those
documents are only released to a registered account, and no scraper changes that.

OPT-IN / not wired into the daily run. The Action installs no browser by default
(the scan is stdlib-only), so this stays inert unless Playwright is present.
Enable it deliberately (see the workflow notes handed over with this change).

   python3 scripts/fetch_js.py "<documents-page-url>"

fetch(doc_url) mirrors fetch_docs.fetch(): returns (files, note) where
files = [(name, bytes, mime)] — so enrich.py can swap it in for gated portals.
"""
import re, sys, urllib.parse

FILE_RE = re.compile(r"\.(pdf|zip|docx?|xlsx?|rtf|7z)(\?|$)", re.I)


def _playwright_available():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def fetch(doc_url, timeout_ms=45000):
    """Render the page, collect links to real files, download them with the
    page's own session (so cookies set during render are carried). Best-effort."""
    if not _playwright_available():
        return [], "playwright not installed — headless fetch disabled"
    from playwright.sync_api import sync_playwright
    host = urllib.parse.urlparse(doc_url).netloc
    files, seen = [], set()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            ctx = browser.new_context(accept_downloads=True,
                                      user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"))
            page = ctx.new_page()
            page.goto(doc_url, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(1500)   # let late XHR-driven lists settle

            # 1) direct links to files rendered into the DOM
            hrefs = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.href)") or []
            targets = [h for h in hrefs if FILE_RE.search(h or "")]

            for url in targets:
                if url in seen:
                    continue
                seen.add(url)
                try:
                    resp = ctx.request.get(url, timeout=timeout_ms)
                    body = resp.body()
                    if body[:4] == b"%PDF" or body[:2] == b"PK" or "application" in (resp.headers.get("content-type") or ""):
                        cd = resp.headers.get("content-disposition", "")
                        name = (re.search(r'filename="?([^"]+)"?', cd) or [None, urllib.parse.unquote(url.rsplit("/", 1)[-1].split("?")[0])])[1]
                        files.append((name or "document", body, resp.headers.get("content-type", "")))
                except Exception:
                    pass

            # 2) download buttons/links that trigger a JS download rather than a href
            if not files:
                for sel in ["a:has-text('Download')", "button:has-text('Download')",
                            "a:has-text('Herunterladen')", "button:has-text('Herunterladen')"]:
                    for el in page.query_selector_all(sel)[:20]:
                        try:
                            with page.expect_download(timeout=timeout_ms) as dl:
                                el.click()
                            d = dl.value
                            path = d.path()
                            with open(path, "rb") as fh:
                                body = fh.read()
                            files.append((d.suggested_filename or "document", body, ""))
                        except Exception:
                            pass
            browser.close()
    except Exception as e:
        return [], f"headless fetch failed — {host}: {e}"

    if files:
        return files, f"downloaded {len(files)} file(s) from {host} via headless browser — verify amendments on the portal"
    return [], f"gated — {host} exposed no public file even to a headless browser (likely login/registration required)"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    fs, note = fetch(sys.argv[1])
    print(note)
    for name, blob, mime in fs:
        print(f"  {name} ({len(blob):,} bytes) {mime}")
