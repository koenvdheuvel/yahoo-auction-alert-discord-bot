# Filter Lab

Filter Lab is the bot's operator UI for labeling the listings each search finds
and testing rules against saved marketplace facts. Open http://127.0.0.1:9101
while the bot is running. The listener is separate from Prometheus on port 9100.

## Sign in and run

Filter Lab has two ways in. With Discord sign-in set up, people sign in with
their Discord account and see only the servers they manage. Without it, one
shared access key opens everything; that is meant for local and standalone use.

### Discord sign-in

The sign-in page sends you to Discord, which asks you to share who you are
(the `identify` scope) and nothing else. Back in Filter Lab, the bot checks
with its own token which of its servers you are in and what your roles there
allow. You get in when you have the Manage Channels permission in at least one
of them. That is the permission the bot's management commands need, such as
`/register`. The server owner and members with Administrator have it too, and
a member in timeout does not. Filter Lab works out the permission for the
whole server from your roles; channel overrides do not count.

You then see only those servers: their searches, listings, labels, rules,
replays, versions, history imports and post removals. A search in another server answers
exactly like one that does not exist. If you manage more than one server, pick
one in the side panel; All listings and its counts follow the picked server.

Discord's access token is used once, to read your ID, name and avatar, and is
then revoked at Discord. Filter Lab does not store it and does not use it to
list your servers. Discord shows its consent screen at every sign-in: Discord
does not document what skipping it does for someone who never approved the
app, so Filter Lab does not ask to skip it. The sign-in uses a `state` value tied to a short-lived cookie, plus
PKCE. Discord's OAuth2 page does not describe PKCE, but Discord accepts it; the
`state` check protects the sign-in either way.

The bot checks your servers again after 5 minutes, on your next request. If
you lost the permission in one server, that server disappears. If you lost it
in all of them, you are signed out and the sign-in page says why. If Discord
does not answer, Filter Lab refuses requests with "can't reach Discord" and
asks again after 30 seconds; it does not fall back on the earlier answer.

Sign-in is refused, with a message on the sign-in page and a
`review_login_denied` log line with the reason, when you are in none of the
bot's servers, lack Manage Channels in all of them, cancel on Discord, or the
sign-in expired or was started in another browser. A sign-in attempt is valid
for 10 minutes, only in the browser that started it, and its cookie is removed
when Discord sends the person back. Filter Lab keeps nothing on the server for
a sign-in in progress: the `state` carries when it started and a signature
over that time and the browser's login cookie, made with a key that is new at
every start of the bot. So starting many sign-ins cannot push out anyone
else's, and a restart only cancels sign-ins that were in progress.

#### Cookies

Discord sends the browser back from discord.com, another site. Browsers leave
out SameSite=Strict cookies on that request, and on any redirect that follows
it. So the sign-in uses a second cookie, `filter_lab_login`, which is
SameSite=Lax, lives 10 minutes and is only sent to `/auth/discord`. When
Discord sends you back, Filter Lab sets the usual Strict session cookie and
answers with a small page that moves on to `/auth/discord/finish` by itself.
That request comes from Filter Lab's own page, so the browser sends the Strict
cookie, and `/auth/discord/finish` checks that it arrived before showing the
UI. If a browser blocks the cookie, the sign-in page says so.

#### Set it up

1. In the [Discord Developer Portal](https://discord.com/developers/applications),
   open the bot's application. For the dev bot that is PosterFinderDev.
2. Under **OAuth2**, **Redirects**, add the address Filter Lab is opened at
   followed by `/auth/discord/callback`. For the dev instance that is
   `https://yahoo.internal.waxdt.com/auth/discord/callback`. It must match
   exactly: https, no trailing slash.
3. Under **OAuth2**, **Client Secret**, reset the secret if it is not shown and
   copy it. The client ID is the application ID; Filter Lab reads it from
   Discord with the bot token, so there is nothing to set for it.
4. Set these in the bot's `.env`, then restart the bot:

   ```bash
   REVIEW_PUBLIC_URL=https://yahoo.internal.waxdt.com
   REVIEW_DISCORD_CLIENT_SECRET=the-client-secret
   # Or keep the secret in a file instead:
   # REVIEW_DISCORD_CLIENT_SECRET_FILE=/run/secrets/filter-lab-client-secret
   ```

   Remove `REVIEW_TOKEN` and `REVIEW_TOKEN_FILE`. An old
   `alerts.db.review-token` file is no longer used and can be deleted.

The bot needs no new permissions, scopes or privileged intents. Startup stops
with a clear error when the secret is set without `REVIEW_PUBLIC_URL` or the
other way round, when the address has a path or uses plain http (only
`localhost` may use http), when both the secret and the secret file are set,
when the access-key settings are still set, or when `BOT_TOKEN` is missing.
The secret is removed from log output if it ever appears there.

Behind a reverse proxy, keep the browser's Host header and send
`X-Forwarded-Proto: https`; traefik does both by default. Without that header
the sign-in button answers with an error that names it, instead of sending the
browser in circles. When someone opens
Filter Lab at another address, such as an SSH tunnel, the sign-in button first
moves them to `REVIEW_PUBLIC_URL`, because Discord only returns to that
address.

#### Searches without a server

Alerts store the server they belong to. Alerts from before that existed were
given their server at startup, from the channels the bot can see. An old alert
whose channel was deleted, or that the bot can no longer see, has no server.
New alerts always have one, because `/register` only works in a server.
Discord sign-in never shows alerts without a server, or history saved without
one. Running `/register` for the same search in its channel again gives the
alert its server. The access key still shows them.

### Access key

Without Discord sign-in, startup creates a random access key in
`<DATABASE_URL>.review-token`, for example `alerts.db.review-token`. Read that
file locally and paste the key into the sign-in form. The file has mode `0600`;
the key is never placed in a URL, browser storage, or application logs. Set
`REVIEW_TOKEN` to provide your own key of at least 16 characters, or
`REVIEW_TOKEN_FILE` to choose another private file location. The access key
sees every server, including searches without one.

### Running Filter Lab

To open an existing database without starting the Discord gateway, polling or
delivery workers:

```bash
python review.py --database alerts.db
```

The command refuses a missing database unless `--init` is explicitly supplied.
It performs the same backed-up migrations as the bot. Run one application
process per database; use the bot's embedded listener when the bot is already
running. With Discord sign-in set up, this mode checks servers through
Discord's REST API with `BOT_TOKEN`, without the gateway.

The UI is a React app in `frontend/`. The Docker image builds it, so a container
needs nothing extra. When the bot or `review.py` runs from a checkout, build the
UI once first (see [Developing the UI](#developing-the-ui)). Until then the page
says how to build it.

Sessions use an HttpOnly, SameSite Strict cookie and expire after 12 hours; at
most 128 are kept, and at most 5 per Discord user, so one person cannot push
everyone else out. Mutations require same-origin JSON requests. Failed
sign-ins are limited to 10 a minute: wrong access keys, and Discord sign-ins
that Discord sent back and that then failed, such as a cancel or a missing
permission. A broken or foreign sign-in link does not count, because anyone can
send those and they would otherwise block sign-in for everyone. The
bot serves the UI's files itself; nothing loads from a CDN. The page's content
security policy allows only those files, plus style tags that carry a new
random value (a nonce) on every page view. Discord avatars and server icons
load from Discord's image server. The default listener binds to loopback. For
remote operation, use an SSH tunnel or a private HTTPS reverse proxy; preserve
the browser's Host and Origin. Cookies are marked Secure when the request
reaching the application uses HTTPS.

### Logs

Sign-in logs `review_login_succeeded` and `review_login_denied` with the
method, the reason and the Discord user ID when it is known.
`review_access_revoked` names the servers someone lost, and
`review_access_check_failed` says Discord did not answer a check. Labels,
publishing, restoring, history imports and queued post removals log
`review_labels_changed`, `review_rules_published`, `review_rules_restored`,
`review_history_imported` and `review_post_removal_queued` with `actor_id`, the
Discord user ID, and `sign_in` (`discord` or `access_key`). Codes, tokens, the PKCE verifier and the
client secret are never logged.

## Rules for wrong products, accessories and bundles

Start with two required groups: one identifies the subject and another
identifies the product type. For example, a BABYMETAL poster profile could use
`BABYMETAL` / `ベビーメタル` as subject aliases and `poster` / `ポスター` as
product aliases. Each group must match, and either alias can satisfy its group.
A shirt containing the subject name then fails the product group.

Use explicit exclusion terms for clear unwanted offers, such as
`フレームのみ` (frame only), `箱のみ` (box only), or `まとめ売り` (bundle).
Choose review groups for ambiguous terms that may also appear in relevant
listings. Review decisions suppress notification; there is no manual approval
and send action in this version. Avoid broad accessory words that also appear
in descriptions of the complete product. These are examples to test against
your history, not rules automatically installed by the app.

Groups support contains, exact and regex terms, any/all matching inside each
group, and required/excluded/review policies. Exclusions take precedence over
review matches. Source selections and optional minimum/maximum prices apply
alongside title rules. Empty source selections allow all three marketplaces.

The Rules tab checks the draft with the server as you type. A problem points at
the group and term at fault, such as "Group 2, Term 3: Invalid regular
expression", and publishing waits until it is fixed. **Edit as JSON** copies a
draft between searches.

Existing Discord filters remain visible. Their original case-sensitive text
and raw regex behavior is preserved. **Include existing filters** controls
whether they apply alongside the profile. A legacy blacklist remains a veto,
and enabled legacy whitelist terms still combine with OR. Disabled migrated
filters remain disabled. Changing those filters in Discord affects future
checks and replay using the current legacy filters; their historical state is
not reconstructed by replay.

## Normalization

The default new profile uses NFKC, Unicode case folding and whitespace
collapsing. For example, `ＢＡＢＹＭＥＴＡＬ　ＰＯＳＴＥＲ` becomes
`babymetal poster`. Optional kana folding converts katakana to hiragana for
matching; it does not translate Japanese text or invent aliases. Each option
can be disabled, and a group's terms can use original-title matching.

Listings retain their original title for display and Discord. Normalization
does not change listing IDs, URLs, model numbers or prices. Candidate snapshots
record normalization version 1 and the resulting normalized title. Regex
syntax is preserved, including uppercase character-class escapes such as
`\D`; patterns use case-insensitive matching when the normalized profile
calls for it. Regex execution has per-pattern and total-evaluation deadlines.

## Browse and label

The side panel lists each search under its Discord channel; **All listings**
shows every search together. A search has four tabs: Listings, Rules, Replay
and Versions. The address keeps the search and the tab, so a reload or a shared
link opens the same place.

Listings shows each listing's latest decision, as a photo grid or as rows.
Filter by title or listing ID, marketplace, decision and label; the filters
show how many listings each choice leaves. **Earlier decisions** also lists
decisions that a later check replaced. Selecting a decision shows why the bot
decided so. Selecting a photo opens the listing's details: original and
compared titles, price, when it was first and last seen, and a link to the
marketplace.

Label listings as relevant, wrong product, accessory, bundle or unsure. Labels
measure draft quality; they do not change the live rules. A label belongs to the
listing: when a later check decides differently, the label moves to the new
decision.

The keyboard covers the whole triage loop. Press `?` in the UI for this list.

| Keys | Action |
| --- | --- |
| `j` / `k`, or the arrow keys | Next or previous listing |
| `1` to `5` | Label relevant, wrong product, accessory, bundle or unsure; the same key again removes the label |
| `0` or Backspace | Remove the label |
| `x` or Space | Select the listing; with Shift, select a range |
| Ctrl A or ⌘ A | Select every loaded listing |
| Esc | Deselect all |
| Enter | Show details |
| `o` | Open the listing on its marketplace |
| `t` | Test the listing's title with the draft |
| `/` | Search |

While listings are selected, the label keys and the bar at the bottom label all
of them at once.

## Drafts, replay and publishing

The draft for each search is kept in the browser until it is published or
discarded. It survives a reload and an expired session, and signing out removes
it. When someone else signs in on the same browser, the earlier person's drafts
are removed. If someone publishes while you edit, the draft says it was based on an older
version: keep it on top of the new version, or discard it.

Use **Test a title** (`t`) for a specific example. Run replay to compare the
published rules with your draft on saved listings. Each row shows the recorded
original decision, the published rules' result and the draft result. Summary
counts include newly allowed/blocked listings, unwanted examples still allowed,
and relevant examples blocked. These counts measure the saved sample, not all
marketplace traffic.

Replay uses each listing's latest decision. It takes the `REVIEW_REPLAY_LIMIT`
most recently seen listings (default and maximum 500), plus up to 1,000 labeled
listings outside them, so older labels keep counting. Processing has a
10-second budget, and the result says when it is partial. Replay does not poll
marketplaces, change listing baselines, queue notifications or simulate old
delivery timelines. Recorded channel-blacklist vetoes remain blocked in both
comparisons; changing blacklist state, subscriptions and stock changes are
outside this eligibility comparison. Invalid, unenriched or truncated listing
snapshots stay in review rather than being treated as fully known facts.

Publish creates an immutable version after checking that the active version
has not changed since you loaded it. If another operator publishes first, the
publish is refused and the draft shows the newer version. Restore creates a new
version from an older profile. A check already in progress finishes with the
profile it captured; the next check uses the newly published profile.
Publication does not resend historical listings, cancel already queued
notifications or reset baselines.

## Removing posts the rules filter

Publishing never deletes a Discord post by itself. To clean up the channel too,
tick **Also remove Discord posts these rules filter** in the Publish dialog, or
use **Remove filtered posts** on the published version under Versions. Both
show a preview first and remove nothing until you confirm.

The preview checks the search's own posts in its channel against the rules,
with the same decision code as checks and Replay, using the listing facts the
bot saved when it posted. **Posts from** limits it to the last 7, 30 (the
default) or 90 days, or all time. Ages come from the Discord message itself, so
posts from before the database conversion keep their real age. The preview
lists the posts with photos and links, counts them by reason, and lets you
untick a reason to keep its posts.

Only posts of listings the rules filter can go. These always stay:

- posts with 🔔 subscribers, because the post is where people unsubscribe;
- posts whose listing facts are incomplete, or whose check ran out of time;
- posts of listings the rules allow or hold for review;
- other searches' posts in the same channel, DMs, and posts the bot has no
  record of.

One run removes at most 1,000 posts, newest first. The preview says when more
match; run it again afterwards for the rest. The preview checks up to 20,000 of
the newest posts in the range within 10 seconds and says when it stopped early.
Confirming checks each chosen post against the published rules again, and asks
you to check again if other rules were published meanwhile.

Removals go through the same queue as posts, so they survive restarts and
retry on errors. New alert posts always go first. Posts under 14 days old are
deleted with Discord's bulk delete, up to 100 per request; that needs the
**Manage Messages** permission in the channel. Older posts, and all posts in a
channel where Discord refuses the bulk delete, go one request each, a few at a
time, so a large run of old posts can take a while. After a refusal the bot
tries bulk again in that channel an hour later. Versions shows the progress of
the latest run. Queued posts of the same listings are cancelled, so
nothing comes back. A removed listing is not blocked the way 🗑️ blocks it: if
later rules allow it again, the bot does not post it again as new, and only a
later price or stock change would post an update. When Filter Lab runs without
the bot (`review.py`), removals wait in the queue until the bot runs. Removed
posts cannot be brought back; the listings and labels in Filter Lab stay. With
Discord sign-in, people preview and remove posts only for searches in the
servers they manage.

## History and storage

New polling saves accepted, filtered, review, blacklisted and invalid
candidates. Accepted candidate history commits in the same transaction
as listing facts, per-alert baselines and delivery jobs. Rejected candidates
create history only.

The archive keeps a row for each decision a listing gets in a search, not for
each check that sees it. Each check sees most listings again; when the decision
matches the listing's latest row, that row gets the latest facts and its
last-seen time instead of a new copy. A different decision adds a row, and the
previous one stays as an earlier decision. Schema version 4 introduced this.
Its migration backs up the database, then folds the repeated rows of older
archives the same way, keeping every labeled row.

The **Import saved history** action explicitly imports up to 1,000 recent
available delivery/listing snapshots. Stable import keys prevent duplicate
imports, and listings the search already has are skipped. Older records lack
their original eligibility decision and are marked incomplete. Previously
rejected listings were never saved by the old pipeline and cannot be
recovered. Import does not send notifications.

Defaults retain 90 days of candidates with a target maximum of 50,000 rows.
Age counts from when a listing was last seen, so listings still in the search
results are kept, and the least recently seen rows go first. Labeled rows are
never removed by retention. The bot's statistics worker prunes at most 1,000
rows per pass, once per minute when caught up, or on successive statistics
ticks while a backlog remains. The limit is a retention target; catch-up is
bounded and can lag sustained heavy capture. Standalone UI mode does not run
this background pruning. Rule-version history is retained independently.
Existing delivery and reaction history retains its previous behavior.

Configuration is listed in [.env.example](../.env.example): `REVIEW_ENABLED`,
`REVIEW_HOST`, `REVIEW_PORT`, `REVIEW_PUBLIC_URL`, `REVIEW_DISCORD_CLIENT_SECRET`,
`REVIEW_DISCORD_CLIENT_SECRET_FILE`, `REVIEW_TOKEN`, `REVIEW_TOKEN_FILE`,
`REVIEW_REPLAY_LIMIT`, `HISTORY_RETENTION_DAYS` and `HISTORY_MAX_ROWS`.

For a local Docker deployment, add `-e REVIEW_HOST=0.0.0.0` and
`-p 127.0.0.1:9101:9101` to the README's container command. This maps the UI to
the host's loopback interface. Without Discord sign-in and with
`DATABASE_URL=/data/alerts.db`, the generated key is
`data/alerts.db.review-token` on the host's mounted data directory.

Behind an HTTPS reverse proxy (for example traefik, which does this by default),
the proxy must send `X-Forwarded-Proto: https`; the UI uses it for the same-origin
check and to mark the session cookie Secure.

## API notes

The UI uses the same JSON API that scripts can call with the session cookie.
`GET /api/candidates` returns newest-first pages of up to 100 rows. Pass the
`next_cursor` of one page as `cursor` to get the next; this neither skips nor
repeats rows when labels or new checks change the list between pages.
`latest=1` keeps each listing's latest decision, and `facets=1` adds the counts
for the filters. `POST /api/candidates/feedback` labels up to 200 listings at
once and reports the ones retention removed meanwhile. `POST /api/rules/validate`
checks a ruleset without saving it. `POST /api/alerts/{id}/posts/removal-preview`
shows which posts a ruleset, or else the published one, filters.
`POST /api/alerts/{id}/posts/removal` queues up to 1,000 chosen posts for removal
under the published version, and `GET` on the same path reports the latest run.
Discord message IDs travel as text, because they do not fit in a JavaScript
number. Errors are JSON with `error` and `message`; ruleset errors add `field`,
such as `groups.1.terms.2`.

`GET /api/session` says whether the browser is signed in and which sign-in this
Filter Lab uses (`method` is `discord` or `access_key`). With Discord it also
returns the `user` and the `guilds` (servers) the person manages. With Discord
sign-in, `guild_id` on `/api/candidates` limits All listings to one of those
servers, and `/api/alerts` totals list each server under `guilds`. A request
gets 401 `access_revoked` when the latest check found that the person lost
every server, and 503 `access_unknown` while Discord does not answer a check.
With Discord sign-in, `POST /api/login` does not exist; a script needs the
session cookie of a browser that signed in.

## Developing the UI

The UI uses React, MUI and TypeScript, built with Vite. It needs Node 22.12 or
newer; CI and the Docker image use Node 24.

```bash
cd frontend
npm ci
npm run build    # writes frontend/dist, which the bot serves
```

For live reloading, run a review server on its usual port and start Vite next
to it. Vite serves the UI on http://127.0.0.1:5173 and forwards `/api` to
`http://127.0.0.1:9101`, or to `FILTER_LAB_BACKEND` when set.

```bash
python review.py --database alerts.db &
cd frontend && npm run dev
```

The Vite server sends no content security policy, so check style and nonce
changes against the built UI served by `review.py`. Before pushing, run the
same checks as CI:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

### Trying Discord sign-in

`devtools/filter_lab_harness.py` runs Filter Lab with Discord sign-in against a
small fake Discord on this computer, so no Discord application is needed. Use a
copy of a database, never the bot's own file:

```bash
cp alerts.db filterlab-scratch.db
python -m devtools.filter_lab_harness --database filterlab-scratch.db --recheck 20
```

Open http://127.0.0.1:9101. The fake Discord runs at http://localhost:9199,
which the browser treats as another site, like discord.com. Its sign-in page
offers five people: alice manages the first server, erin manages every server,
bob is a member without Manage Channels, carol is in no server, and dave owns
the last server. http://localhost:9199/fake removes members, changes roles and
can make Discord stop answering. `--recheck` shortens the 5 minutes between
access checks. The servers come from the alerts in the database; to try the
server picker, give some alerts in the copy another `guild_id`. The tests use
the same fake (`devtools/fake_discord.py`), so nothing in them reaches Discord.

