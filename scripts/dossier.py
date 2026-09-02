#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dossie de uma RFP: puxa o registo completo, localiza os documentos,
monta a timeline e escreve um briefing + um prompt pronto para o Claude analisar.
   python3 scripts/dossier.py <notice-id>        # 25763636 (DE) ou 588408-2026 (TED)
"""
import io, json, os, re, sys, zipfile, datetime, urllib.request, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = {"User-Agent": "LabsCubed-RFP-Radar/1.0 (leandro@labscubed.com)"}
TED_API = "https://api.ted.europa.eu/v3/notices/search"

def get(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()

# ---------- fonte TED ------------------------------------------------------
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
    for attempt in range(5):                       # TED devolve 429 sob carga
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r); break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4: raise
            time.sleep(2 ** attempt)
    n = (d.get("notices") or [None])[0]
    if not n: raise SystemExit(f"TED: aviso {pub} nao encontrado")
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
            # NOTA: /xml e /pdf do TED sao assincronos (HTTP 202, corpo vazio na 1a chamada).
            # A pagina de detalhe e o caminho fiavel; traz o link do portal do comprador.
            "docs": [f"https://ted.europa.eu/en/notice/-/detail/{pub}"]}

# ---------- fonte Alemanha (eForms XML no export diario) --------------------
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
        # 1o <Name> = ContractingParty (comprador); o <Name> dentro de
        # ProcurementProject = objeto do contrato. Nao confundir os dois.
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
    raise SystemExit(f"DE: aviso {nid} nao encontrado nos exports dos ultimos 45 dias")

# ---------- timeline -------------------------------------------------------
def timeline(rec):
    today = datetime.date.today()
    if not rec.get("deadline"):
        return ["**Prazo nao publicado no registo estruturado** — confirmar na pagina "
                "do edital ANTES de planear. Toda a timeline abaixo depende disso."], None
    dl = datetime.date.fromisoformat(rec["deadline"][:10])
    left = (dl - today).days
    # marcos contados para tras a partir da data-limite
    marks = [(dl - datetime.timedelta(days=n), lbl) for n, lbl in [
        (0,  "PRAZO FINAL — submissao no portal (submeter 24h antes; upload falha)"),
        (2,  "Revisao final: assinaturas, anexos, formato, conformidade"),
        (7,  "Proposta tecnica + comercial fechada internamente"),
        (14, "Ultimo dia util para PERGUNTAS ao comprador (verificar prazo real no edital)"),
        (18, "Decisao bid / no-bid + montagem das referencias e certificados"),
        (21, "Analise tecnica: matriz de requisitos vs CubeTen/CubeOne/CubeFlex"),
    ]]
    lines = [f"**Prazo final: {dl.isoformat()} — faltam {left} dias**", ""]
    for d, lbl in sorted(marks):
        flag = "✅" if d < today else ("⚠️ HOJE" if d == today else "")
        lines.append(f"- `{d.isoformat()}` {'(passou) ' if d < today else ''}{lbl} {flag}")
    if left < 21:
        lines += ["", f"> ⚠️ **Janela curta ({left} dias).** Os marcos acima estao comprimidos — "
                      "decidir bid/no-bid nas proximas 48h."]
    return lines, left

# ---------- relatorio ------------------------------------------------------
def report(rec):
    tl, left = timeline(rec)
    docs = rec.get("docs") or []
    md = [f"# Dossie RFP — {rec['title'][:120]}", "",
          "| | |", "|---|---|",
          f"| **ID** | `{rec['id']}` ({rec['source']}) |",
          f"| **Comprador** | {rec['buyer'] or '—'} |",
          f"| **Pais** | {rec.get('country') or '—'} |",
          f"| **Publicado** | {rec.get('published') or '—'} |",
          f"| **Prazo** | {rec.get('deadline') or '**nao publicado — confirmar**'} |",
          f"| **CPV** | {', '.join(rec['cpv']) or '—'} |",
          f"| **Procedimento** | {rec.get('procedure') or '—'} |",
          f"| **Valor estimado** | {rec.get('value') or '—'} |",
          f"| **Edital** | {rec['url']} |", "",
          "## Objeto", "", (rec.get("desc") or "—")[:2500], "",
          "## Timeline", ""] + tl + ["", "## Documentos da licitacao", ""]
    md += [f"- {u}" for u in docs] or \
          ["- Nenhum link direto no registo estruturado. Abrir a pagina do edital "
           "e descarregar manualmente (muitos portais exigem registo/'Teilnahme aktivieren')."]
    md += ["", "## Proximos passos", "",
        "1. **Confirmar o prazo real** na pagina do edital (o registo estruturado nem sempre o traz).",
        "2. **Bid / no-bid** — usar o crivo tecnico abaixo.",
        "3. Se BID: registar no portal do comprador e ativar a participacao "
        "(na Alemanha, 'Teilnahme aktivieren' — so assim se recebem as alteracoes ao edital).",
        "4. Descarregar todos os anexos e correr a analise do Claude (prompt no fim deste ficheiro).",
        "5. Submeter as perguntas ao comprador dentro do prazo — e a unica alavanca para "
        "influenciar especificacoes escritas a medida de um concorrente.", "",
        "## Crivo tecnico LabsCubed", "",
        "| Criterio | Limite | Verificar no edital |",
        "|---|---|---|",
        "| Forca max. | CubeTen 10 kN · CubeOne 1 kN | pedido >10 kN = **no-bid** |",
        "| Material | plasticos rigidos, borrachas, elastomeros | metal/betao = **no-bid** |",
        "| Ensaio | tracao, flexao, rasgo | dureza, impacto/Charpy, fadiga = **no-bid** |",
        "| Normas | ASTM D638/D412/D624/D790 · ISO 527/37/178 | outras = avaliar |",
        "| Alongamento | ate 1000% | acima = **no-bid** |",
        "| Automacao | ate 15 provetes/ciclo | pedido maior = avaliar |",
        "| Espaco/peso | 0,8 × 1,2 m · 113 kg | verificar restricoes do laboratorio |",
        "| Software | Portal cloud + AI Suite; SAP/Uncountable/Alpha Workbench | "
        "exigencia on-premise = risco |", "",
        "## Prompt para analise do Claude", "", "```",
        f"Analisa os documentos da RFP em {ROOT}/dossiers/{rec['id']}/ para a LabsCubed",
        "(CubeTen: tracao plasticos rigidos 10kN ASTM D638/ISO 527; CubeOne: tracao/rasgo",
        "borrachas 1kN ASTM D412/ISO 37/D624; CubeFlex: flexao ASTM D790/ISO 178;",
        "Portal cloud + AI Suite). Produz:",
        "1. Veredito bid/no-bid com justificacao, usando o crivo tecnico do dossie.",
        "2. Matriz requisito-a-requisito: exigencia | CubeTen/One/Flex cumpre? | evidencia | lacuna.",
        "3. Lacunas tecnicas e como as endereçar (parceiro, opcao, excecao declarada).",
        "4. Criterios de adjudicacao e peso de cada um; onde ganhamos e onde perdemos pontos.",
        "5. Requisitos de elegibilidade (referencias, certificados, volume de negocios, seguros)",
        "   e quais deles nao cumprimos hoje.",
        "6. Perguntas a submeter ao comprador (especificacoes ambiguas ou escritas a medida",
        "   de um concorrente).",
        "7. Estrutura secao-a-secao da proposta, com quem responde o que e em quantos dias.",
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
                print(f"  vazio (assincrono), abrir no browser: {u}", file=sys.stderr); continue
            ext = ".pdf" if b[:4] == b"%PDF" else ".html"
            (outdir / f"doc{i}{ext}").write_bytes(b)
            print(f"  baixado: doc{i}{ext} ({len(b)} bytes) <- {u}", file=sys.stderr)
        except Exception as e:
            print(f"  NAO baixou {u}: {e}", file=sys.stderr)
    print(report(rec))
    print(f"\n--> {outdir}/dossier.md", file=sys.stderr)
