# Página `/rfp` do portal — o que falta

Tudo o resto está feito e a correr na cloud. Esta é a única peça que precisa de
tocar no repo do portal.

## Dados: já estão prontos

Três tabelas no projeto Supabase **LabsCubed // Claude** (`grozewxrymeiruhggcdy`),
com o mesmo RLS de `prospects` — `labscubed_automation` escreve, `authenticated` lê
via `portal.is_team()`. Não é preciso migração nenhuma.

- **`rfps`** — uma linha por procedimento. Campos-chave: `title`, `buyer`,
  `buyer_country`, `score`, `tier` (HOT/WARM/COLD), `deadline`, `deadline_is_proxy`,
  `value_eur`, `cpv[]`, `why_matched`, `disqualified`, `disqualification_reason`,
  `status` (new/reviewing/bid/no_bid/submitted/won/lost), `url`, `summary`,
  `timeline` (jsonb), `requirement_matrix` (jsonb), `proposal_skeleton`.
- **`rfp_documents`** — anexos por edital (`rfp_id`, `filename`, `url`, `extracted_text`).
- **`rfp_feedback`** — ratings do comercial (`rating` 1–5, `label`, `comment`).

## O que a página precisa de ter

**`/rfp` (lista)** — ordenada por `deadline` ascendente, HOT primeiro:

| Coluna | Nota |
|---|---|
| Título + comprador | link para o detalhe |
| País | `buyer_country` |
| Score + tier | chip colorido: HOT vermelho, WARM âmbar |
| Prazo + dias restantes | ⚠️ se `deadline_is_proxy` for true, marcar como *não confirmado* |
| Valor | `value_eur` |
| Status | editável — é aqui que o comercial move para `bid`/`no_bid` |

Filtros: tier, status, país, e um toggle **"mostrar desqualificados"** (por defeito
escondidos, mas visíveis — a razão da desqualificação é informação útil).

**`/rfp/[id]` (detalhe)** — o que a tabela do Slack já liga:
objeto, porque casou (`why_matched`), timeline, matriz de requisitos, anexos de
`rfp_documents`, e um bloco para dar rating (escreve em `rfp_feedback`).

## Duas coisas a não esquecer

1. **`deadline_is_proxy`.** Quando é `true`, a data vem de `publicOpeningDate`, não do
   prazo real de submissão — o export alemão não traz o BT-131. Mostrar como *a
   confirmar*, nunca como facto. Planear em cima de uma data errada perde o edital.
2. **`rfp_feedback` precisa de política de INSERT** para `authenticated`. Hoje só
   existe SELECT — sem isso, o bloco de rating falha em silêncio.

## Depois de publicar

Definir a variable `PORTAL_BASE_URL` no repo `labscubed-rfp-radar`
(Settings → Secrets and variables → Actions → Variables), ex.
`https://portal.labscubed.com`. Sem ela, a tabela do Slack liga ao edital original
em vez da página interna.
