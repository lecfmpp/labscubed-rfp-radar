---
name: rfp-digest
description: Post the daily RFP Radar digest to #rfp-agent. Reads today's tender notices straight from Supabase and publishes the table through the Slack connector. Runs weekdays at 07:15 UTC, after the GitHub Actions scan at 06:00. Needs no repo, no shell and no local machine.
---

# RFP Digest

Publishes the day's detected tender notices to `#rfp-agent` (`C0BUL9KGD52`), in the
same shape as the BDR Agent batch digest.

**This runs entirely on connectors — Supabase and Slack.** No repository, no Python,
no shell, no local machine. The scan that produces the data runs separately on GitHub
Actions (`lecfmpp/labscubed-rfp-radar`, weekdays 06:00 UTC) and writes to Supabase;
this routine only reads what is there and posts it.

**Never invent a row.** If the queries come back empty or fail, say so in the channel.
A fabricated tender wastes a salesperson's day.

## Step 1 — read the batch

Supabase project `grozewxrymeiruhggcdy` (**LabsCubed // Claude**).

```sql
select id, title, buyer, buyer_country, score, tier, deadline,
       deadline_is_proxy, disqualified, disqualification_reason, url
from rfps
where batch_date = current_date
order by score desc, deadline asc nulls last;
```

```sql
select * from rfp_batches where batch_date = current_date;
```

If `rfp_batches` has no row for today, **the scan did not run.** Do not post a digest
with zeroed numbers — report that in the channel and point at
`lecfmpp/labscubed-rfp-radar` → Actions → RFP Radar.

## Step 2 — build the message

Post with `slack_send_message`. Keep the markdown table exactly as written; the
connector converts it into a real Slack table. Do not escape the structural `|`.

```
:satellite_antenna: _New RFP Batch — {today}_
RFPs saved: _{total}_ · HOT (≥60): _{hot}_ · WARM: _{warm}_ · Disqualified: _{dq}_ · Avg score: _{avg}_ · Window: {days} days

_Scanned {scanned} notices (DE Datenservice {scanned_de} + TED/EU {scanned_ted}) · CPV matched: {by_cpv} · full-text only: {by_fulltext} · new since last run: {new_rows}_

:warning: _{n} with a deadline inside 14 days — decide bid/no-bid this week._

| # | Notice | Buyer | Country | Score | Deadline | Left | Link |
|---|---|---|---|---|---|---|---|
| 1 | {title, 70 chars} | {buyer, 38 chars} | {buyer_country} | {score, no decimals} | {deadline}{⚠️ if proxy} | {days}d | [open]({link}) |

_⚠️ = deadline is a proxy (public opening date); confirm on the notice page before planning._

_{dq} disqualified by the technical screen ({first reason}) — see `rfps` ·_
_full batch in Supabase `rfps` ·_ :satellite_antenna: _RFP Radar_
```

Rules for filling it in:

- **Exclude `disqualified = true` rows from the table.** Count them in the footer with
  the first reason. Disqualified means the notice really is about materials testing but
  falls outside the product envelope (>10 kN, metal or concrete, hardness, impact,
  fatigue). That is different from not matching, and the team should still see that it
  happened and why.
- **`Link`** is `https://labscubed.portal.ca/sales/rfp/{id}` once the portal page is
  live; until then use the row's `url`.
- **`Left`** is days from today to `deadline`; `—` when there is no deadline,
  `expired` when it has passed.
- **Append ⚠️ to the deadline when `deadline_is_proxy` is true**, and include the
  legend line. That date is the public opening date, not the real submission deadline —
  the German export does not carry field BT-131. Never present it as confirmed.
- Drop the `:warning:` line when nothing is inside 14 days, and the legend line when
  nothing is a proxy.
- If more than 25 rows survive, post the first 25 and continue in a thread reply, with
  `…table continues in thread (26–{n}) · ` prefixed to the footer.

## Step 3 — post even when it is empty

If there are no new opportunities, replace the table with:

```
_No new opportunities within the criteria in this window._
```

and post it anyway. A quiet day is a result: it tells the team the radar ran and found
nothing, which is different from the radar being broken. Those two must never look the
same in the channel.

## Step 4 — log the run

Insert into `automation_runs`: `project` = `rfp-radar`, `task` = `slack-digest`,
`status`, `rows_affected` = the number of notices posted, `completed_at` = now.

## Feedback loop

When someone in the channel calls a result useless, or says the radar missed something,
record it in `rfp_feedback` (`rfp_id`, `rater_name`, `rating` 1-5, `label` one of
`good` / `noise` / `missed`, `comment`). Those ratings are what recalibrate the scoring
weights. Log the exchange in `skill_learnings` with `task_id` = `rfp-digest`.

## Note on the table

If a draft ever shows raw `|` characters, that is the draft composer, which does not
support markdown tables. Sent messages render correctly. Do not "fix" the formatting
based on how a draft looks.
