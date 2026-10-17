# Filter Lab

Filter Lab is the bot's operator UI for seeing what each search finds and what
the bot decided, and for testing rules against saved marketplace facts. Open
http://127.0.0.1:9101 while the bot is running. The listener is separate from
Prometheus on port 9100.

## Sign in and run

By default startup creates a random access key in
`<DATABASE_URL>.review-token`, for example `alerts.db.review-token`. Read that
file locally and paste the key into the sign-in form. The file has mode `0600`;
the key is never placed in a URL, browser storage, or application logs. Set
`REVIEW_TOKEN` to provide your own key of at least 16 characters, or
`REVIEW_TOKEN_FILE` to choose another private file location.

To open an existing database without starting the Discord gateway, polling or
delivery workers:

```bash
python review.py --database alerts.db
```

The command refuses a missing database unless `--init` is explicitly supplied.
It performs the same backed-up migrations as the bot. Run one application
process per database; use the bot's embedded listener when the bot is already
running.

The UI is a React app in `frontend/`. The Docker image builds it, so a container
needs nothing extra. When the bot or `review.py` runs from a checkout, build the
UI once first (see [Developing the UI](#developing-the-ui)). Until then the page
says how to build it.

The key grants operator access to every alert and archived record. Sessions use
an HttpOnly, SameSite Strict cookie and expire after 12 hours. Mutations require
same-origin JSON requests, and failed logins are rate limited. The bot serves
the UI's files itself; nothing loads from a CDN. The page's content security
policy allows only those files, plus style tags that carry a new random value
(a nonce) on every page view. The default listener binds to loopback. For
remote operation, use an SSH tunnel or a private HTTPS reverse proxy; preserve
the browser's Host and Origin. Cookies are marked Secure when the request
reaching the application uses HTTPS. Multi-user roles and Discord OAuth are
future extensions, not part of this operator interface.

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

## Browse listings

The side panel lists each search under its Discord channel; **All listings**
shows every search together. A search has four tabs: Listings, Rules, Replay
and Versions. The address keeps the search and the tab, so a reload or a shared
link opens the same place.

Listings shows each listing's latest decision, as a photo grid or as rows.
Filter by title or listing ID, marketplace and decision; the filters show how
many listings each choice leaves. **Earlier decisions** also lists decisions
that a later check replaced. Selecting a decision shows why the bot decided so.
Selecting a photo opens the listing's details: original and compared titles,
price, when it was first and last seen, and a link to the marketplace.

Keys move through the listings. Press `?` in the UI for this list.

| Keys | Action |
| --- | --- |
| `j` / `k`, or the arrow keys | Next or previous listing |
| Enter | Show details |
| `o` | Open the listing on its marketplace |
| `t` | Test the listing's title with the draft |
| `/` | Search |

## Drafts, replay and publishing

The draft for each search is kept in the browser until it is published or
discarded. It survives a reload and an expired session, and signing out removes
it. If someone publishes while you edit, the draft says it was based on an older
version: keep it on top of the new version, or discard it.

Use **Test a title** (`t`) for a specific example. Run replay to compare the
published rules with your draft on saved listings. Each row shows the recorded
original decision, the published rules' result and the draft result. The
summary counts the listings the draft newly allows or newly blocks. These
counts cover the saved sample, not all marketplace traffic.

Replay uses the latest decision of the `REVIEW_REPLAY_LIMIT` most recently seen
listings (default and maximum 500). Processing has a 10-second budget, and the
result says when it is partial. Replay does not poll
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
posts cannot be brought back; the listings in Filter Lab stay.

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
archives the same way. It also deletes the listing labels that earlier versions
of Filter Lab saved, because Filter Lab no longer uses them.

The **Import saved history** action explicitly imports up to 1,000 recent
available delivery/listing snapshots. Stable import keys prevent duplicate
imports, and listings the search already has are skipped. Older records lack
their original eligibility decision and are marked incomplete. Previously
rejected listings were never saved by the old pipeline and cannot be
recovered. Import does not send notifications.

Defaults retain 90 days of candidates with a target maximum of 50,000 rows.
Age counts from when a listing was last seen, so listings still in the search
results are kept, and the least recently seen rows go first. The bot's
statistics worker prunes at most 1,000 rows per pass, once per minute when
caught up, or on successive statistics ticks while a backlog remains. The limit
is a retention target; catch-up is bounded and can lag sustained heavy capture. Standalone UI mode does not run
this background pruning. Rule-version history is retained independently.
Existing delivery and reaction history retains its previous behavior.

Configuration is listed in [.env.example](../.env.example): `REVIEW_ENABLED`,
`REVIEW_HOST`, `REVIEW_PORT`, `REVIEW_TOKEN`, `REVIEW_TOKEN_FILE`,
`REVIEW_REPLAY_LIMIT`, `HISTORY_RETENTION_DAYS` and `HISTORY_MAX_ROWS`.

For a local Docker deployment, add `-e REVIEW_HOST=0.0.0.0` and
`-p 127.0.0.1:9101:9101` to the README's container command. This maps the UI to
the host's loopback interface. With `DATABASE_URL=/data/alerts.db`, the generated
key is `data/alerts.db.review-token` on the host's mounted data directory.

Behind an HTTPS reverse proxy (for example traefik, which does this by default),
the proxy must send `X-Forwarded-Proto: https`; the UI uses it for the same-origin
check and to mark the session cookie Secure.

## API notes

The UI uses the same JSON API that scripts can call with the session cookie.
`GET /api/candidates` returns newest-first pages of up to 100 rows. Pass the
`next_cursor` of one page as `cursor` to get the next; this neither skips nor
repeats rows when new checks change the list between pages. `latest=1` keeps
each listing's latest decision, and `facets=1` adds the counts for the filters.
`POST /api/rules/validate` checks a ruleset without saving it. `POST /api/alerts/{id}/posts/removal-preview`
shows which posts a ruleset, or else the published one, filters.
`POST /api/alerts/{id}/posts/removal` queues up to 1,000 chosen posts for removal
under the published version, and `GET` on the same path reports the latest run.
Discord message IDs travel as text, because they do not fit in a JavaScript
number. Errors are JSON with `error` and `message`; ruleset errors add `field`,
such as `groups.1.terms.2`.

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
