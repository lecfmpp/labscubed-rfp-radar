#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica o lote diario em #rfp-agent, no mesmo formato do BDR Agent.
   python3 scripts/slack_post.py data/saved_2026-09-02.json [--stats stats.json]
Env: SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, PORTAL_BASE_URL
"""
import json, os, sys, datetime, urllib.request

TOKEN   = os.environ["SLACK_BOT_TOKEN"]
CHANNEL = os.environ["SLACK_CHANNEL_ID"]
PORTAL  = os.environ.get("PORTAL_BASE_URL", "").rstrip("/")
API     = "https://slack.com/api/chat.postMessage"
MAX_ROWS = 25          # o resto continua na thread, como faz o BDR

def api(payload):
    req = urllib.request.Request(API, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=45) as r:
        d = json.load(r)
    if not d.get("ok"): raise SystemExit(f"Slack recusou: {d.get('error')}")
    return d

def days_left(deadline):
    if not deadline: return "—"
    try:
        n = (datetime.date.fromisoformat(deadline[:10]) - datetime.date.today()).days
        return f"{n}d" if n >= 0 else "expirado"
    except ValueError:
        return "—"

def table_block(rows):
    """Bloco table nativo do Slack: max 100 linhas x 20 colunas."""
    head = ["#", "Edital", "Comprador", "País", "Score", "Prazo", "Resta", "Portal"]
    def cell(t): return {"type": "raw_text", "text": str(t)[:180]}
    trs = [[cell(h) for h in head]]
    for i, r in enumerate(rows, 1):
        link = f"{PORTAL}/rfp/{r['id']}" if PORTAL else (r.get("url") or "")
        trs.append([
            cell(i),
            cell((r.get("title") or "")[:70]),
            cell((r.get("buyer") or "—")[:38]),
            cell(r.get("buyer_country") or "—"),
            cell(f"{float(r.get('score') or 0):.0f}"),
            cell((r.get("deadline") or "—")[:10]),
            cell(days_left(r.get("deadline"))),
            {"type": "rich_text", "elements": [{"type": "rich_text_section",
                "elements": [{"type": "link", "url": link, "text": "abrir"}]}]}
            if link else cell("—"),
        ])
    return {"type": "table", "rows": trs}

def build(rows, stats):
    today = datetime.date.today().isoformat()
    hot  = [r for r in rows if r["tier"] == "HOT"]
    warm = [r for r in rows if r["tier"] == "WARM"]
    dq   = [r for r in rows if r.get("disqualified")]
    live = [r for r in rows if not r.get("disqualified")]
    avg  = (sum(float(r["score"]) for r in rows) / len(rows)) if rows else 0
    soon = [r for r in live if r.get("deadline") and
            0 <= (datetime.date.fromisoformat(r["deadline"][:10]) - datetime.date.today()).days <= 14]

    head = (f":satellite_antenna: _Novo lote de RFPs — {today}_\n"
            f"RFPs guardadas: _{len(rows)}_ · HOT (≥60): _{len(hot)}_ · WARM: _{len(warm)}_ · "
            f"Desqualificadas: _{len(dq)}_ · Score médio: _{avg:.1f}_ · Janela: {stats.get('days', 3)} dias")

    prov = (f"_Analisados {stats.get('scanned', 0):,} avisos "
            f"(DE Datenservice {stats.get('scanned_de', 0):,} + TED/UE {stats.get('scanned_ted', 0):,}) · "
            f"match por CPV: {stats.get('by_cpv', 0)} · só por texto livre: {stats.get('by_fulltext', 0)} · "
            f"já adjudicados excluídos: {stats.get('excluded_awarded', 0)} · "
            f"novos desde a última corrida: {len(rows)}_").replace(",", ".")

    blocks = [{"type": "markdown", "text": head}, {"type": "markdown", "text": prov}]
    if soon:
        blocks.append({"type": "markdown", "text":
            f":warning: _{len(soon)} com prazo dentro de 14 dias — decidir bid/no-bid esta semana._"})
    shown = live[:MAX_ROWS]
    if shown:
        blocks.append(table_block(shown))
    else:
        blocks.append({"type": "markdown",
                       "text": "_Nenhuma oportunidade nova dentro dos critérios nesta janela._"})

    cont = (f"…tabela continua na thread ({MAX_ROWS+1}–{len(live)}) · " if len(live) > MAX_ROWS else "")
    foot = f"_{cont}lote completo no Supabase `rfps` ·_ :satellite_antenna: _RFP Radar_"
    if dq:
        foot = (f"_{len(dq)} desqualificadas pelo crivo técnico "
                f"({dq[0].get('disqualification_reason','')[:60]}…) — ver `rfps` ·_\n") + foot
    blocks.append({"type": "markdown", "text": foot})
    return blocks, head, live

def main(path, stats_path=None):
    rows = json.load(open(path))
    stats = json.load(open(stats_path)) if stats_path and os.path.exists(stats_path) else {}
    blocks, fallback, live = build(rows, stats)
    try:
        d = api({"channel": CHANNEL, "blocks": blocks, "text": fallback})
    except SystemExit:                       # bloco table recusado: cai para texto
        d = api({"channel": CHANNEL, "text": fallback +
                 "\n\n(tabela indisponível — ver Supabase `rfps`)"})
    print(f"[slack] publicado ts={d['ts']}")
    if len(live) > MAX_ROWS:                 # resto na thread, como o BDR
        api({"channel": CHANNEL, "thread_ts": d["ts"],
             "blocks": [table_block(live[MAX_ROWS:])],
             "text": f"RFPs {MAX_ROWS+1}–{len(live)}"})
    return d

if __name__ == "__main__":
    s = sys.argv[sys.argv.index("--stats") + 1] if "--stats" in sys.argv else None
    main(sys.argv[1], s)
