# Portal `/sales/rfp` page — what is left to build

Everything else is done and running in the cloud. This is the only piece that touches
the portal repo.

## The data is already there

Three tables in the **LabsCubed // Claude** Supabase project (`grozewxrymeiruhggcdy`),
with the same RLS as `prospects` — `labscubed_automation` writes, `authenticated` reads
via `portal.is_team()`. No migration needed.

- **`rfps`** — one row per procedure. Key fields: `title`, `buyer`, `buyer_country`,
  `score`, `tier` (HOT/WARM/COLD), `deadline`, `deadline_is_proxy`, `value_eur`,
  `cpv[]`, `why_matched`, `disqualified`, `disqualification_reason`, `status`
  (new/reviewing/bid/no_bid/submitted/won/lost), `url`, `summary`, `timeline` (jsonb),
  `requirement_matrix` (jsonb), `proposal_skeleton`.
- **`rfp_documents`** — attachments per notice (`rfp_id`, `filename`, `url`,
  `extracted_text`).
- **`rfp_feedback`** — sales ratings (`rating` 1–5, `label`, `comment`). SELECT and
  INSERT are both open to team members.

## What the page needs

**`/sales/rfp` (list)** — sorted by `deadline` ascending, HOT first:

| Column | Note |
|---|---|
| Title + buyer | links to the detail page |
| Country | `buyer_country` |
| Score + tier | coloured chip: HOT red, WARM amber |
| Deadline + days left | flag as *unconfirmed* when `deadline_is_proxy` is true |
| Value | `value_eur` |
| Status | editable — this is where sales moves a row to `bid` / `no_bid` |

Filters: tier, status, country, and a **"show disqualified"** toggle — hidden by
default, but reachable: the disqualification reason is useful information.

**`/sales/rfp/[id]` (detail)** — the destination the Slack table already links to:
subject, why it matched (`why_matched`), timeline, requirement matrix, attachments
from `rfp_documents`, and a rating block writing to `rfp_feedback`.

## Two things not to miss

1. **`deadline_is_proxy`.** When it is `true` the date comes from `publicOpeningDate`,
   not the real submission deadline — the German export does not carry BT-131. Show it
   as *to be confirmed*, never as fact. Planning against a wrong date loses the tender.
2. **Do not render `description`, `title` or `why_matched` as HTML.** They are buyer-authored
   text pulled from public feeds. Escape them.

## After publishing

Set the `PORTAL_BASE_URL` variable in the `labscubed-rfp-radar` repo
(Settings → Secrets and variables → Actions → Variables) to
`https://portal.labscubed.ca/sales`. The digest then links to
`{PORTAL_BASE_URL}/rfp/{id}`.
