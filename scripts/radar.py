#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LabsCubed RFP Radar - consolidated daily scan.
   python3 scripts/radar.py [--days 3]
Sources: Germany (oeffentlichevergabe.de Open Data) + EU (TED API).
State lives in Supabase, deduplicated by unique(source, notice_id) - see
scripts/push_supabase.py. Nothing is written back to the repo.
"""
import json, os, sys, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)
import fetch_de, fetch_ted, fetch_sam


def main(days=3):
    today = datetime.date.today()
    rows = []
    stats = {"days": days, "scanned": 0, "scanned_de": 0, "scanned_ted": 0,
             "scanned_sam": 0, "by_cpv": 0, "by_fulltext": 0}

    # --- Germany: one monthly export per month the window touches -------
    # One request instead of one per day. The export refuses connections from
    # some cloud IP ranges, so every extra request is another chance to fail.
    since = (today - datetime.timedelta(days=days - 1)).isoformat()
    months, d = [], today - datetime.timedelta(days=days - 1)
    while d <= today:
        m = d.strftime("%Y-%m")
        if m not in months: months.append(m)
        d += datetime.timedelta(days=1)
    for m in months:
        try:
            r, tot = fetch_de.run(m, since=since)
            rows += r; stats["scanned_de"] += tot
            print(f"  DE {m} (since {since}): {tot} notices -> {len(r)} qualified",
                  file=sys.stderr)
        except Exception as e:
            print(f"  DE {m}: FAILED ({e})", file=sys.stderr)
            stats.setdefault("source_errors", []).append(f"DE {m}: {e}")

    # --- EU / TED -----------------------------------------------------
    try:
        r, tot = fetch_ted.run(days)
        rows += r; stats["scanned_ted"] += tot
        print(f"  TED {days}d: {tot} notices in target CPVs -> {len(r)} qualified",
              file=sys.stderr)
    except Exception as e:
        print(f"  TED: FAILED ({e})", file=sys.stderr)

    # --- US / SAM.gov (keyless public API) ----------------------------
    try:
        r, tot = fetch_sam.run(days)
        rows += r; stats["scanned_sam"] = tot
        print(f"  SAM {days}d: {tot} notices scanned -> {len(r)} qualified",
              file=sys.stderr)
    except Exception as e:
        print(f"  SAM: FAILED ({e})", file=sys.stderr)
        stats.setdefault("source_errors", []).append(f"SAM: {e}")

    stats["scanned"] = stats["scanned_de"] + stats["scanned_ted"] + stats.get("scanned_sam", 0)
    stats["by_cpv"] = sum(1 for r in rows if r.get("found_by", "cpv") in ("cpv", "psc"))
    stats["by_fulltext"] = sum(1 for r in rows if r.get("found_by") == "fulltext")
    rows.sort(key=lambda r: (-r["score"], r.get("deadline") or "9999"))

    stamp = today.isoformat()
    (ROOT / "data").mkdir(exist_ok=True)
    json.dump(rows, open(f"data/radar_{stamp}.json", "w"), ensure_ascii=False, indent=1)
    json.dump(stats, open(f"data/stats_{stamp}.json", "w"), indent=1)

    hot  = [r for r in rows if r["tier"] == "HOT"]
    warm = [r for r in rows if r["tier"] == "WARM"]
    md = [f"# RFP Radar - {stamp}", "",
          f"**{len(hot)} HOT** (review today) · **{len(warm)} WARM** (triage) · "
          f"{days}-day window · sources: Germany + TED/EU", ""]
    for label, group in (("HOT - open and review today", hot),
                         ("WARM - quick triage", warm)):
        if not group: continue
        md += [f"## {label}", ""]
        for r in group:
            dl, left = r.get("deadline") or "-", ""
            if dl != "-":
                try:
                    left = f" ({(datetime.date.fromisoformat(dl[:10]) - today).days} days left)"
                except ValueError: pass
            val = f" · ~EUR {r['value_eur']:,.0f}" if r.get("value_eur") else ""
            md += [f"### [{r['score']}] {r['title'][:150]}",
                   f"- **Buyer:** {r['buyer'] or '-'}",
                   f"- **Tender deadline:** {dl}{left}{val}",
                   f"- **Why it matched:** {r['why']}",
                   f"- **CPV:** {', '.join(r['cpv'][:6])}",
                   f"- **Source:** {r['source']} · [open notice]({r['url']})", ""]
    if not rows:
        md += ["_No new notices within the criteria in this window._", ""]

    (ROOT / "reports").mkdir(exist_ok=True)
    out = ROOT / "reports" / f"radar_{stamp}.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n--> {out}", file=sys.stderr)
    return len(hot), len(warm)


if __name__ == "__main__":
    days = 3
    if "--days" in sys.argv: days = int(sys.argv[sys.argv.index("--days") + 1])
    main(days)
