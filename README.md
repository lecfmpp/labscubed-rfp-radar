# RFP Radar — LabsCubed

Detects public tender notices for materials-testing equipment across Germany and the
EU, qualifies them against the product envelope, writes them to Supabase and posts a
table to `#rfp-agent`. **Runs entirely on GitHub Actions** — no local machine involved.

```
GitHub Actions (cron 06:00 UTC, weekdays)
  └─ radar.py             scan DE Datenservice + TED/EU, score, write the batch
     └─ push_supabase.py  upsert into `rfps`, log to `automation_runs`
        └─ slack_post.py  table in #rfp-agent, NEW notices only
```

There is no state file and nothing is written back to the repo. What has already been
seen lives in the `unique(source, notice_id)` constraint on the `rfps` table.

## Setup

**Secrets** (Settings → Secrets and variables → Actions → Secrets):

| Secret | Where to get it |
|---|---|
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | same page → `service_role` key |
| `SLACK_BOT_TOKEN` | Slack app → OAuth & Permissions → Bot token (`xoxb-…`), scope `chat:write` |
| `SLACK_CHANNEL_ID` | `C0BUL9KGD52` (#rfp-agent) |

**Variable** (same screen, Variables tab):

| Variable | Purpose |
|---|---|
| `PORTAL_BASE_URL` | portal origin, e.g. `https://portal.labscubed.com`. Without it the Slack table links to the original notice instead of the internal page. |

The Slack bot must be invited to the channel: `/invite @<bot>` in `#rfp-agent`.

## Running it manually

Actions → **RFP Radar** → *Run workflow* (takes the window in days).

```bash
python3 scripts/radar.py --days 3          # scan only, writes reports/radar_<date>.md
python3 scripts/dossier.py 588408-2026     # full dossier for one notice (TED)
python3 scripts/dossier.py 25763636        # full dossier for one notice (Germany)
```

## Sources (both public, no authentication)

| Source | Endpoint | Coverage |
|---|---|---|
| Germany — Datenservice Öffentlicher Einkauf | `GET oeffentlichevergabe.de/api/notice-exports?pubDay=YYYY-MM-DD&format=csv.zip` | Federal, Länder and municipal — **above and below** the EU thresholds |
| EU — TED | `POST api.ted.europa.eu/v3/notices/search` | 27 member states, **above** the thresholds only |

Measured volumes: ~985 notices/day in Germany; 19,222 notices per 30 days in the
target CPVs on TED.

### Why the BAM website is not scraped

BAM's tender page is institutional — it holds no notices. Its actual tenders live on
e-Vergabe (`evergabe-online.de/search.html?...&ids=22`, where `ids=22` is BAM), which
runs on Apache Wicket: the search is a stateful POST with session-scoped component
paths, so it is **not parameterisable by URL** (tested — four URL variants, none work).
BAM publishes in parallel to both sources above, which have APIs. Using the API is
cheaper and more reliable than driving Wicket.

On FireCrawl: Germany alone publishes ~30,000 notices/month. Scraping the detail pages
would cost ~30,000 credits/month; the API returns the same 30,000 **in a single
request**. FireCrawl is reserved for fetching attachments from portals with no API
(5–20 pages/month, inside the free tier).

## Qualification

Three layers in `scripts/criteria.py`:

1. **CPV by prefix** — `3854*` (includes 38542000 servo-hydraulic), `3850*`, `3897*`, `3890*`, `38400*`
2. **Keywords** in DE/EN/FR/ES/PT/IT plus standards (ASTM D638/D412/D624/D790, ISO 527/37/178)
3. **Exclusions** — concrete, asphalt, soil, welding, hardness, Charpy, maintenance contracts

Thresholds: **≥60 HOT** · **40–59 WARM** · **<40 discarded**. Only notices whose
`formType` is `competition`, `change` or `planning` pass — award notices (`can-*`) are
excluded.

**Disqualification is distinct from "did not match"**: the notice is in our field but
falls outside the envelope (>10 kN, metal/concrete, hardness/impact/fatigue, elongation
>1000%). It lands in `rfps.disqualified` + `disqualification_reason`, so the team can
report "we saw 40, we ruled out 38, and here is why".

Measured precision over August 2026: **22,765 notices → 2 open opportunities**.

### The full-text pass is not optional

TED's second pass found a *"Static materials testing machine"* from Fraunhofer
classified under **CPV 42990000** (miscellaneous machinery) — outside every laboratory
CPV. A CPV-only filter would have missed it.

## Known limitations

- **The German CSV export does not carry the tender submission deadline** (BT-131).
  `publicOpeningDate` is used as a proxy and flagged with `deadline_is_proxy=true`. The
  exact deadline comes from the eForms XML or the notice page, via `dossier.py`.
- **TED's `/xml` and `/pdf` are asynchronous** (HTTP 202, empty body on the first call).
- **TED returns 429 under load** — exponential backoff, five attempts.
- **TED descriptions are in the original language.** Titles are translated to English,
  but descriptions in Polish, Czech or Hungarian will not match the current keywords.
- **The current day's export does not exist yet** (HTTP 400). Run with `--days ≥ 2`.

## Calibration

`rfp_feedback` follows the `icp_feedback` pattern: the sales team rates each result
(`good` / `noise` / `missed`) and those ratings recalibrate the weights in
`criteria.py`. Worth running two weeks before widening the geography — widening before
the criteria are proven multiplies noise, not opportunities.
