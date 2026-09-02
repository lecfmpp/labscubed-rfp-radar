# Prompt — build the `/rfp` page in the LabsCubed portal

> Paste this into the Claude session that owns the portal repo. It is self-contained:
> everything it needs about the data already exists in Supabase.

---

Build an **RFP** section in the portal at `https://portal.labscubed.ca/sales/rfp`,
matching the existing branding, layout conventions and auth gating used by the other
internal pages. Two routes: a list at `/sales/rfp` and a detail at `/sales/rfp/[id]`.

The detail route is what the Slack digest links to, as
`https://portal.labscubed.ca/sales/rfp/{rfps.id}` — keep that shape.

## The data already exists — do not create tables

Supabase project `grozewxrymeiruhggcdy` (**LabsCubed // Claude**). RLS already
matches `prospects`: `labscubed_automation` writes, `authenticated` reads through
`portal.is_team()`. `rfp_feedback` also allows INSERT for team members. No migration
is needed.

### `rfps` — one row per tender procedure

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | primary key, used in the detail route |
| `source` | text | `DE/oeffentlichevergabe` or `EU/TED` |
| `notice_id`, `procedure_id` | text | identifiers at the source |
| `url` | text | the original public notice |
| `title`, `description` | text | buyer-authored, **escape before rendering** |
| `buyer`, `buyer_city`, `buyer_country` | text | contracting authority |
| `cpv` | text[] | CPV codes |
| `published`, `deadline` | date | |
| `deadline_is_proxy` | bool | **see the warning below** |
| `value_eur` | numeric | estimated value |
| `score` | numeric | 0–150ish |
| `tier` | text | `HOT` (≥60) · `WARM` (40–59) · `COLD` |
| `why_matched` | text | which CPV / keyword / standard triggered it |
| `found_by` | text | `cpv` or `fulltext` |
| `disqualified` | bool | ruled out by the technical screen |
| `disqualification_reason` | text | human-readable reason |
| `summary`, `proposal_skeleton` | text | filled in later by the dossier step |
| `timeline`, `requirement_matrix` | jsonb | filled in later; may be null |
| `status` | text | `new` `reviewing` `bid` `no_bid` `submitted` `won` `lost` |
| `owner` | text | who picked it up |
| `batch_date` | date | which scan produced it |

`rfp_documents`: `rfp_id`, `filename`, `url`, `mime`, `bytes`, `extracted_text`.
`rfp_feedback`: `rfp_id`, `rater_name`, `rating` (1–5), `label`, `comment`.

## `/sales/rfp` — the list

Default view: `disqualified = false`, sorted by `tier` (HOT first) then `deadline`
ascending. This is a work queue, not an archive — the thing nearest its deadline is
the thing that matters.

Columns: **Title** (links to detail) with `buyer` underneath · **Country** ·
**Score + tier** as a coloured chip · **Deadline + days left** · **Value** ·
**Status** as an inline editable control.

Status must be editable directly from the list. Moving a row to `bid` or `no_bid` is
the single most common action on this page and should not require opening the detail
view.

Filters: tier, status, country, and a **"show disqualified"** toggle — off by
default, but present. The disqualification reason is useful information, not noise:
it tells the team the radar considered something and why it ruled it out.

Empty state: say the radar ran and found nothing new, not "no data". A quiet day and
a broken pipeline must not look the same.

## `/sales/rfp/[id]` — the detail

This is where the Slack digest links to. Sections, in this order:

1. **Header** — title, buyer, country, source with a link to the original notice.
2. **Countdown** — deadline and days remaining, given real visual weight. If
   `deadline_is_proxy` is true, this is where the warning lives.
3. **Why it matched** — `why_matched`, plus `found_by` and the CPV codes. This is
   what lets a person trust or dismiss the match in a few seconds.
4. **Subject** — `description`.
5. **Screening** — if `disqualified`, show `disqualification_reason` prominently;
   this row is informational, not actionable.
6. **Timeline** — render `timeline` jsonb when present; otherwise say the dossier
   has not been generated yet.
7. **Requirements** — render `requirement_matrix` jsonb as a table when present.
   It may contain `[GAP]` and `[NEEDS HUMAN]` markers: surface those, do not hide
   them. They are the point.
8. **Documents** — from `rfp_documents`.
9. **Feedback** — rating 1–5, a label (`good` / `noise` / `missed`) and a comment,
   writing to `rfp_feedback`. Explain in one line that this recalibrates the scoring.

## Three things not to get wrong

1. **`deadline_is_proxy`.** When true, the date is the public opening date, not the
   real submission deadline — the German export does not carry field BT-131. Show it
   as *to be confirmed*, never as a plain date. Planning against a wrong deadline
   loses the tender outright. This is the highest-consequence detail on the page.
2. **Escape all buyer text.** `title`, `description`, `buyer` and `why_matched` come
   from public feeds written by third parties. Never render them as HTML.
3. **Disqualified is not deleted.** Hidden by default, one toggle away, with the
   reason visible. The team should be able to answer "did we ever see that tender?"
   with a yes and a reason.

## Not needed

No create or delete. The radar owns row creation; people only change `status`,
`owner` and add feedback.
