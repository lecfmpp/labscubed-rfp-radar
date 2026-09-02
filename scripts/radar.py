#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RFP Radar LabsCubed — varredura diaria consolidada.
   python3 scripts/radar.py [--days 3]
Fontes: Alemanha (oeffentlichevergabe.de Open Data) + UE (TED API).
Guarda estado em data/seen.json para nunca alertar o mesmo edital duas vezes.
"""
import json, os, sys, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)
import fetch_de, fetch_ted

# O estado (que avisos ja foram vistos) vive no Supabase, deduplicado pela
# constraint unique(source, notice_id) — ver scripts/push_supabase.py.

def main(days=3):
    today = datetime.date.today()
    rows = []
    stats = {"days": days, "scanned": 0, "scanned_de": 0, "scanned_ted": 0,
             "by_cpv": 0, "by_fulltext": 0, "excluded_awarded": 0}

    # --- Alemanha: um export por dia do periodo -----------------------
    for i in range(days):
        d = (today - datetime.timedelta(days=i)).isoformat()
        try:
            r, tot = fetch_de.run(d)
            rows += r; stats["scanned_de"] += tot
            print(f"  DE {d}: {tot} avisos -> {len(r)} qualificados", file=sys.stderr)
        except Exception as e:
            print(f"  DE {d}: FALHOU ({e})", file=sys.stderr)

    # --- UE / TED ----------------------------------------------------
    try:
        r, tot = fetch_ted.run(days)
        rows += r; stats["scanned_ted"] += tot
        print(f"  TED {days}d: {tot} avisos nos CPV-alvo -> {len(r)} qualificados", file=sys.stderr)
    except Exception as e:
        print(f"  TED: FALHOU ({e})", file=sys.stderr)

    stats["scanned"] = stats["scanned_de"] + stats["scanned_ted"]
    stats["by_cpv"] = sum(1 for r in rows if r.get("found_by", "cpv") == "cpv")
    stats["by_fulltext"] = sum(1 for r in rows if r.get("found_by") == "fulltext")
    new = rows
    new.sort(key=lambda r: (-r["score"], r.get("deadline") or "9999"))

    stamp = today.isoformat()
    json.dump(new, open(f"data/radar_{stamp}.json", "w"), ensure_ascii=False, indent=1)
    json.dump(stats, open(f"data/stats_{stamp}.json", "w"), indent=1)

    hot  = [r for r in new if r["tier"] == "HOT"]
    warm = [r for r in new if r["tier"] == "WARM"]
    md = [f"# RFP Radar — {stamp}", "",
          f"**{len(hot)} HOT** (analisar hoje) · **{len(warm)} WARM** (triagem) · "
          f"janela {days} dia(s) · fontes: Alemanha + TED/UE", ""]
    for label, group in (("🔴 HOT — abrir e analisar hoje", hot),
                         ("🟡 WARM — triagem rapida", warm)):
        if not group: continue
        md += [f"## {label}", ""]
        for r in group:
            dl = r.get("deadline") or "—"
            left = ""
            if dl != "—":
                try:
                    left = f" (faltam {(datetime.date.fromisoformat(dl[:10]) - today).days} dias)"
                except ValueError: pass
            val = f" · ~{r['value_eur']:,.0f} EUR" if r.get("value_eur") else ""
            md += [f"### [{r['score']}] {r['title'][:150]}",
                   f"- **Comprador:** {r['buyer'] or '—'}",
                   f"- **Prazo de proposta:** {dl}{left}{val}",
                   f"- **Por que casou:** {r['why']}",
                   f"- **CPV:** {', '.join(r['cpv'][:6])}",
                   f"- **Fonte:** {r['source']} · [abrir edital]({r['url']})", ""]
    if not new:
        md += ["_Nenhum edital novo dentro dos criterios nesta janela._", ""]

    out = ROOT / "reports" / f"radar_{stamp}.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n--> {out}", file=sys.stderr)
    return len(hot), len(warm)

if __name__ == "__main__":
    days = 3
    if "--days" in sys.argv: days = int(sys.argv[sys.argv.index("--days") + 1])
    main(days)
