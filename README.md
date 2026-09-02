# RFP Radar — LabsCubed

Deteta editais públicos de equipamento de ensaio de materiais na Alemanha e na UE,
qualifica-os contra o envelope técnico dos produtos, grava no Supabase e publica
uma tabela em `#rfp-agent`. **Corre inteiramente em GitHub Actions** — nenhuma
máquina local envolvida.

```
GitHub Actions (cron 06:00 UTC, dias úteis)
  └─ radar.py         varre DE Datenservice + TED/UE, pontua, escreve o lote
     └─ push_supabase.py   upsert em `rfps`, regista em `automation_runs`
        └─ slack_post.py   tabela em #rfp-agent, só com os editais NOVOS
```

Estado: não há ficheiro de estado nem escrita no repo. O que já foi visto vive na
constraint `unique(source, notice_id)` da tabela `rfps`.

## Configuração

**Secrets** (Settings → Secrets and variables → Actions → Secrets):

| Secret | Onde obter |
|---|---|
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | mesma página → `service_role` key |
| `SLACK_BOT_TOKEN` | app Slack → OAuth & Permissions → Bot token (`xoxb-…`), scope `chat:write` |
| `SLACK_CHANNEL_ID` | `C0BUL9KGD52` (#rfp-agent) |

**Variable** (mesmo ecrã, separador Variables):

| Variable | Para quê |
|---|---|
| `PORTAL_BASE_URL` | base do portal, ex. `https://portal.labscubed.com`. Sem isto a tabela do Slack liga ao edital original em vez da página interna. |

O bot do Slack tem de ser convidado ao canal: `/invite @<bot>` em `#rfp-agent`.

## Correr à mão

Actions → **RFP Radar** → *Run workflow* (aceita a janela em dias).

## Fontes (ambas públicas, sem autenticação)

| Fonte | Endpoint | Cobertura |
|---|---|---|
| Alemanha — Datenservice Öffentlicher Einkauf | `GET oeffentlichevergabe.de/api/notice-exports?pubDay=YYYY-MM-DD&format=csv.zip` | Federal + Länder + municípios, **acima e abaixo** dos limiares UE |
| UE — TED | `POST api.ted.europa.eu/v3/notices/search` | 27 estados-membros, só **acima** dos limiares |

Volumes medidos: ~985 avisos/dia na Alemanha; 19.222/30 dias nos CPV-alvo no TED.

### Porque não se raspa o site da BAM

A página da BAM é institucional. Os editais dela estão no e-Vergabe
(`evergabe-online.de/search.html?...&ids=22`), que corre em Apache Wicket: a busca é
POST com estado de sessão, **não é parametrizável por URL** (testado). A BAM publica
em paralelo nas duas fontes acima, que têm API — mais barato e mais fiável.

Sobre FireCrawl: só a Alemanha publica ~30.000 avisos/mês. Raspar as páginas de
detalhe custaria ~30.000 créditos/mês; a API entrega os mesmos 30.000 **num pedido**.
FireCrawl fica reservado para buscar anexos em portais sem API (5–20 páginas/mês,
dentro do tier grátis).

## Qualificação

Três camadas em `scripts/criteria.py`:

1. **CPV por prefixo** — `3854*` (inclui 38542000 servo-hidráulico), `3850*`, `3897*`, `3890*`, `38400*`
2. **Palavras-chave** DE/EN/FR/ES/PT/IT + normas (ASTM D638/D412/D624/D790, ISO 527/37/178)
3. **Exclusões** — betão, asfalto, solo, soldadura, dureza, Charpy, contratos de manutenção

Corte: **≥60 HOT** · **40–59 WARM** · **<40 descartado**. Só passam avisos com
`formType` em `competition`/`change`/`planning` — adjudicações (`can-*`) ficam de fora.

**Desqualificação** é distinta de "não deu match": o edital é da nossa área mas cai
fora do envelope (>10 kN, metal/betão, dureza/impacto/fadiga, alongamento >1000%).
Fica em `rfps.disqualified` + `disqualification_reason`, para se poder reportar
"vimos 40, desqualificámos 38, e porquê".

Precisão medida em agosto/2026: **22.765 avisos → 2 oportunidades abertas**.

### A busca full-text é obrigatória

A segunda passagem do TED encontrou uma *"Static materials testing machine"* da
Fraunhofer classificada com **CPV 42990000** (maquinaria diversa) — fora de qualquer
CPV de laboratório. Só o filtro por CPV teria perdido este edital.

## Dossiê por edital

```bash
python3 scripts/dossier.py 588408-2026     # TED
python3 scripts/dossier.py 25763636        # Alemanha
```

Puxa o registo completo, descarrega os documentos, e escreve um briefing com
timeline calculada para trás a partir do prazo (D−21 análise, D−14 perguntas ao
comprador, D−2 revisão), o crivo bid/no-bid, e um prompt pronto para a análise
detalhada com o Claude.

## Limitações conhecidas

- **O export CSV alemão não traz a data-limite de submissão** (BT-131). Usa-se
  `publicOpeningDate` como proxy e marca-se `deadline_is_proxy=true`. O prazo exato
  vem do eForms XML ou da página do edital, via `dossier.py`.
- **`/xml` e `/pdf` do TED são assíncronos** (HTTP 202, corpo vazio na 1.ª chamada).
- **TED devolve 429 sob carga** — backoff exponencial de 5 tentativas.
- **Descrições no TED estão no idioma original.** Títulos são traduzidos para EN, mas
  descrições em polaco/checo/húngaro não casam com as keywords atuais.
- **O export do dia corrente ainda não existe** (HTTP 400). Correr com `--days ≥ 2`.

## Calibração

`rfp_feedback` segue o molde de `icp_feedback`: o comercial marca cada resultado
(`good` / `noise` / `missed`) e esses ratings recalibram os pesos em `criteria.py`.
Vale correr duas semanas antes de alargar a geografia — alargar antes de saber se os
critérios estão certos multiplica o ruído, não as oportunidades.
