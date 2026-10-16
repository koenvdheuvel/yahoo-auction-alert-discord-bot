# Yahoo Auction, Mercari, Surugaya Discord Bot

A Discord bot that searches Yahoo Auction, Mercari, and Surugaya through FromJapan, posts new listings and qualifying changes, and sends subscribed users update DMs.

The implementation separates marketplace adapters, notification policy, SQLite persistence, durable Discord delivery, and runtime supervision. See the [architecture reference](docs/architecture.md) and [monitoring guide](docs/monitoring.md).

## Run locally

Python 3.11 is the supported runtime, matching the container and CI.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set BOT_TOKEN in .env.
python main.py
```

Configuration is validated before startup. `.env.example` lists the polling, concurrency, timeout, retry, and monitoring settings. `DATABASE_URL` is a SQLite filename, not a connection URL. The default interval is 1,800 seconds and up to four checks run concurrently.

Slash commands register and remove channel-scoped queries, manage title filters, list alerts, and clean up bot messages. Mutating commands require Manage Channels. Trash reactions blacklist a listing in that channel; bell reactions subscribe the user to listing changes, and removing the bell unsubscribes. Historical tracked messages remain valid reaction targets.

Discord integration uses Hikari 2.6.0 and Lightbulb 3.2.6. Hikari owns the gateway;
Lightbulb owns slash commands, typed options, dependency injection, and execution
hooks. Commands are synchronized before polling starts. The gateway requests only
guild and guild-reaction events, with no privileged intents required.

Price decreases greater than ¥500, buyout changes greater than ¥500 in either direction, and stock changes whose new quantity exceeds 1 generate updates. `PRICE_CHANGE_THRESHOLD` configures the price threshold.

## Dashboard and title normalization

The dashboard opens at **http://127.0.0.1:9101** when the bot starts. With
Discord sign-in set up (`DASHBOARD_PUBLIC_URL` and `DASHBOARD_DISCORD_CLIENT_SECRET`),
anyone in one of the bot's servers signs in with Discord. People with Manage
Channels in a server manage it there; everyone else manages only their own 🔔
notifications. Behind a reverse proxy, list it in `DASHBOARD_TRUSTED_PROXIES`.
Without Discord sign-in, sign in with the key in
`alerts.db.dashboard-token` next to your configured database, or set
`DASHBOARD_TOKEN` in `.env`. The generated file is private and excluded from Git
and container builds. `DASHBOARD_ENABLED=false` disables the listener. The container
image includes the built UI; from a checkout, build it once with Node 22.12 or
newer:

```bash
cd frontend && npm ci && npm run build
```

The dashboard looks like Discord: a server list, each server's channels in
Discord's order with their searches under them, and pages for what the slash
commands and reactions do. Managers add and remove searches, see a channel's
posts, hide listings as 🗑️ does, clean up channels, and see each search's last
checks and waiting posts. Everyone sees and stops their own 🔔 follows.

It also shows what each search found as a photo grid or as rows, with the
bot's decision and its reasons. You label wrong products, accessories and
bundles from the keyboard, one listing or a selection at a time, edit grouped
rules, and compare drafts against saved history before publishing. Each required group
must match; aliases within a group can match any term. Exclusion groups veto a
listing, while review groups hold ambiguous listings for inspection. Published
versions can be restored as a new version.

New rules use Unicode NFKC, case folding, and whitespace normalization by
default, with optional kana folding. Original titles and listing identities stay
intact. Existing Discord title filters keep their original matching behavior;
the UI shows whether those filters participate alongside the new rules.

You can also run the UI against an existing database without starting Discord or
marketplace polling:

```bash
python dashboard.py --database alerts.db
```

The bot records new candidates automatically. The UI can explicitly import a
bounded sample of older saved listings; those records lack the original filter
decisions and never reconstruct alerts that were previously discarded. Replay
and publishing do not send notifications. See the [dashboard guide](docs/dashboard.md)
for rule design, replay limits, authentication, and retention.

## Metrics and health

Monitoring is enabled by default on `127.0.0.1:9100`:

- `/metrics`: Prometheus exposition for polling, providers, database operations, delivery, backlog, gateway connectivity, and event-loop lag.
- `/health/live`: event loop can respond and shutdown has not started.
- `/health/ready`: Discord, supervised workers, database, and poll freshness are healthy.

Logs are structured JSON with cycle, alert, source, and delivery correlation. Per-alert check metrics use `alert_id`; the separate `auction_bot_alert_info` lookup maps that ID to the search query and channel for Grafana display. Other operational metric labels exclude query text, listing/user IDs, and request URLs. Example scrape configuration and alert rules are in [monitoring/](monitoring/).

## Existing databases and delivery recovery

The original schema is migrated at startup after writing a timestamped backup next to the database. Keep the whole database directory persistent. Old filters whose matcher was never saved are retained but disabled: inspect `/filters get`, then delete and recreate them with text or regex selected.

Discord sends are durably queued and retried independently. Failed jobs can be inspected and retried after their cause is fixed:

```bash
python manage.py --database alerts.db outbox-list --status failed
python manage.py --database alerts.db outbox-retry --id 123
```

One application process should own a database. Discord acceptance followed by a crash before local acknowledgment can still produce a duplicate; see the [delivery and migration details](docs/architecture.md).

## Container

```bash
docker build -t auction-bot .
# Put .env in the data directory; DATABASE_URL is overridden for the mount.
docker run -d --name auction-bot --restart unless-stopped \
  -v "$PWD/data:/data" -v "$PWD/data/.env:/app/.env:ro" \
  -e DATABASE_URL=/data/alerts.db auction-bot
```

To scrape from outside the container, set `MONITORING_HOST=0.0.0.0` and expose the monitoring port on the intended private interface/network. The endpoint has no authentication. The monitoring guide describes scrape placement; metrics are not publicly published by default.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .
python -m pytest -q

cd frontend
npm ci
npm run lint && npm run typecheck && npm test && npm run build
```

Tests use temporary SQLite files and local HTTP fixtures with fake Discord REST; they do not contact marketplace or Discord services. GitHub Actions runs both sets of checks before deploying pushes to `develop` (the dev bot) and `master` (production). The [dashboard guide](docs/dashboard.md#developing-the-ui) explains live reloading for the UI.

This project originated as a rewrite of [vlourme's bot](https://github.com/vlourme/yahoo-auction-alert-discord-bot). It is licensed under the [GNU General Public License](LICENSE).
