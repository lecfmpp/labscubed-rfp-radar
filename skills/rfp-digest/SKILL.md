---
name: rfp-digest
description: Post the daily RFP Radar digest to #rfp-agent. Reads today's tender notices from Supabase and publishes the table via the Slack connector. Runs weekdays at 07:15 UTC, after the GitHub Actions scan at 06:00.
---

# RFP Digest

Publishes the day's detected tender notices to `#rfp-agent`, in the same shape as the
BDR Agent batch digest.

**This skill does not scan anything.** The scan runs on GitHub Actions
(`lecfmpp/labscubed-rfp-radar`, weekdays 06:00 UTC) and writes to Supabase. This skill
only reads what is already there and posts it. If the scan failed, say so — do not
compose a digest from anything else.

## Prerequisites

- Repo `lecfmpp/labscubed-rfp-radar` cloned locally.
- Env: `SUPABASE_URL=https://grozewxrymeiruhggcdy.supabase.co` and
  `SUPABASE_SERVICE_KEY` (the `service_role` key).
- Optional: `PORTAL_BASE_URL` — once the portal `/rfp` page exists, the table links
  there instead of to the original public notice.
- Slack connector. **No bot, no app, no token** — the message posts as the user with
  "Sent using @Claude", the same path as every other LabsCubed automation.

## Steps

1. **Render the message.** From the repo root:

   ```bash
   python3 scripts/slack_digest.py
   ```

   It prints a ready-to-send markdown message and talks to Slack not at all. It reads
   both the notices (`rfps`) and the funnel stats (`rfp_batches`) from Supabase, so it
   works on any machine regardless of where the scan ran.

2. **Post it verbatim** to `#rfp-agent` (`C0BUL9KGD52`) with `slack_send_message`.

   Do not rewrite, summarise, reorder or "improve" it. The formatting is deliberate
   and matches the BDR Agent digest. In particular, do not touch the `|` characters —
   `slack_send_message` converts the markdown table into a real Slack table.

3. **Post even when it is empty.** If the message says no new opportunities, post it
   anyway. A quiet day is a result: it tells the team the radar ran and found nothing,
   which is different from the radar being broken. Those two must never look the same.

4. **Log the run** in Supabase `automation_runs`:
   `project` = `rfp-radar`, `task` = `slack-digest`, `status`, `rows_affected` = the
   number of notices posted.

## If something goes wrong

- **The script errors.** Post the error to `#rfp-agent` and stop. Never invent rows or
  reconstruct a digest from memory — a fabricated tender wastes a salesperson's day.
- **No `rfp_batches` row for today.** The scan did not run. Check the Actions run
  (`lecfmpp/labscubed-rfp-radar` → Actions → RFP Radar) and report that in the channel
  rather than posting a digest with zeroed stats.
- **The table renders as raw pipes.** Only happens in the draft composer, which does
  not support markdown tables. On a real send it renders. If it ever fails on a real
  send, re-run with `--format code` for a fixed-width block instead.

## What the message contains

Header with the counts, a provenance line showing the funnel (how many notices were
scanned, how many matched by CPV, how many only by full-text), a warning line if
anything is inside 14 days, the table, and a footer.

Two details worth understanding before you touch the output:

- **Disqualified notices are excluded from the table** and counted in the footer with
  their reason. Disqualified means the notice is genuinely about materials testing but
  falls outside the product envelope (>10 kN, metal/concrete, hardness/impact/fatigue).
  That is different from not matching, and the team should still see it happened.
- **A ⚠️ next to a deadline means the date is a proxy** — the public opening date, not
  the real submission deadline, because the German export does not carry field BT-131.
  Never present those dates as confirmed.

## Feedback loop

When someone in the channel calls a result useless or says the radar missed something,
record it in Supabase `rfp_feedback` (`rfp_id`, `rater_name`, `rating` 1-5, `label` one
of `good` / `noise` / `missed`, `comment`). Those ratings are what recalibrate the
scoring weights in `scripts/criteria.py`. Also log the exchange in `skill_learnings`
with `task_id` = `rfp-digest`.
