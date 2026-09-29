# Truwealth Viral Content Radar

In-house tool for the founder. Every 15 minutes it checks Google Trends, Indian finance news, X trends (through public mirror sites), about 90 Indian finance YouTube channels, Reddit and big market moves. When a finance topic spikes, it emails a brief: what is trending, the evidence, how urgent it is, and content angles for LinkedIn, X and Instagram. A digest arrives every day at 08:00 IST.

Design: `docs/superpowers/specs/2026-09-26-viral-content-radar-design.md`

## Setup (one time)

1. **Sender account.** Use a dedicated Google account. Turn on 2-Step Verification, then create an app password (Google Account > Security > App passwords) and keep the 16-character password.
2. **GitHub.** Push this repository to a public GitHub repository. In Settings > Secrets and variables > Actions, add:
   - `SMTP_USER`: the sender Gmail address
   - `SMTP_APP_PASSWORD`: the app password
   - `ALERT_TO`: recipient addresses, comma-separated
3. **Start.** In the Actions tab, enable workflows, then run `radar` and `digest` once with "Run workflow". After that they run on schedule. HOT alerts start 24 hours after the first run, once the radar has some history. Until the three secrets exist, both workflows run in dry-run mode: the radar keeps building its history but sends nothing, and each run shows a warning. Adding the secrets switches them to real emails with no other change.
4. **Phone alerts.** In the founder's Gmail, create a filter for mail from the sender address: "Never send it to Spam" and "Always mark it as important". With the Gmail app set to notify for important mail, HOT alerts arrive as push notifications.

## Local use

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest
python -m radar run --dry-run --db local.db
python -m radar digest --dry-run --db local.db
```

`--dry-run` writes the emails to `out/` instead of sending them.

## Tuning

- Thresholds, weights, caps, cooldowns and warm-up: `config/settings.yaml`
- Topics and keywords: `config/topics.yaml`; content angles: `config/angles.yaml`
- YouTube channels: `config/channels.yaml` (the `id` is the channel id that starts with `UC`)
- Dated events for the digest: `config/events.yaml`
- Feeds and queries: `config/sources.yaml`

## Ghostwriter handoff (optional)

The radar can also hand topics to the LinkedIn ghostwriter (private repository Truwealth-Ghostwriter). It appends one row per HOT, capped or rising topic to the "Radar topics" tab of the ghostwriter's Google Sheet, placing values by header name. It never creates the tab and never edits rows.

A rising topic is Emerging or Peaking, at or above the watch threshold, with no alert this run and none in the last 24 hours. Each one is sent at most once every 24 hours, and at most 10 are sent per day. The limits are under `handoff` in `config/settings.yaml`.

Add two Actions secrets:

- `GHOST_SHEET_ID`: the ghostwriter Sheet's id (the long part of its URL)
- `RADAR_SA_JSON`: the JSON key of the `radar-inbox` service account. Tab protection, set up from the ghostwriter app, lets it edit only the Radar topics tab.

Without the secrets the radar behaves exactly as before. Handoff errors are logged and never fail a run.
