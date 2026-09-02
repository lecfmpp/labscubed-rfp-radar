# Slack digest — Claude routine

The scan and the Supabase write run on GitHub Actions. **Slack is posted by a
scheduled Claude routine**, exactly like every other LabsCubed automation: the
message appears as Leandro with *"Sent using @Claude"*. There is no Slack app, no
bot user and no token anywhere in this repo.

## Why the split

| Step | Runs where | Why |
|---|---|---|
| Scan 2 sources, score ~1,000 notices/day | GitHub Actions | Purely deterministic. No model needed, so no tokens are spent on it. |
| Upsert into `rfps` | GitHub Actions | Same run, one service key. |
| Post the table to `#rfp-agent` | Claude routine | Uses the Slack connector that already exists. Nothing new to authorise. |

The routine reads `rfps` rather than a file, so it can post even if the scan ran
hours earlier — and re-running it never double-posts, because only rows whose
`batch_date` is today are selected.

## Routine prompt

Schedule this weekdays at 07:15 UTC (after the 06:00 scan):

```
Post the RFP Radar digest to #rfp-agent (channel C0BUL9KGD52).

1. Run: python3 scripts/slack_digest.py
   in the labscubed-rfp-radar repo, with SUPABASE_URL and SUPABASE_SERVICE_KEY set.
   It prints a ready-to-send markdown message and talks to nothing.
2. Post that output verbatim to #rfp-agent with slack_send_message.
   Do not rewrite, summarise or reorder it — the formatting is deliberate and
   matches the BDR Agent digest.
3. If the message says no new opportunities, post it anyway. A quiet day is a
   result: it tells the team the radar ran and found nothing, which is different
   from the radar being broken.
4. Log the run in Supabase `automation_runs` with project 'rfp-radar',
   task 'slack-digest'.

Never invent rows. If the script fails, say so in the channel with the error
rather than composing a digest from memory.
```

## If the routine has no shell

Some routine hosts cannot run Python. In that case, query Supabase directly:

```
select * from rfps
where batch_date = current_date
order by score desc, deadline asc;
```

and build the table with these columns: `#`, Notice (`title`), Buyer (`buyer`),
Country (`buyer_country`), Score (`score`), Deadline (`deadline` — append ⚠️ when
`deadline_is_proxy` is true), Left (days from today), Link (`PORTAL_BASE_URL`/rfp/`id`,
falling back to `url`). Exclude rows where `disqualified` is true from the table and
report their count in the footer instead.
