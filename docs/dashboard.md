# Dashboard

The dashboard is the bot's web app. Server managers use it for what the slash
commands and reactions do: add and remove searches, look at each channel's
posts, hide listings, clean up channels and see how the searches are doing. It
is also where they see what each search finds and what the bot decided, and
test rules against saved marketplace facts. Everyone in one of the bot's servers can use it to
manage their own 🔔 notifications. Open http://127.0.0.1:9101 while the bot is
running. The listener is separate from Prometheus on port 9100.

The page is called after the bot, with "Dashboard": "PosterFinder Dashboard",
or just "Dashboard" while the bot's name is not known. `APP_NAME` and
`app_title()` in `dashboard.py` are the one place that name is made.

## Sign in and run

The dashboard has two ways in. With Discord sign-in set up, people sign in with
their Discord account: they manage the servers where they have Manage Channels,
and in the bot's other servers they manage only their own 🔔 notifications.
Without it, one shared access key opens everything except notifications, which
belong to a Discord user; that is meant for local and standalone use.

### Discord sign-in

The sign-in page sends you to Discord, which asks you to share who you are
(the `identify` scope) and nothing else. Back in the dashboard, the bot checks
with its own token which of its servers you are in and what your roles there
allow. Anyone who is in at least one of the bot's servers gets in. What you may
do is decided per server:

- **Manager:** you have Manage Channels for the whole server, worked out from
  your roles. That is the permission the bot's management commands need, such
  as `/register`. The server owner and members with Administrator have it too.
  You see the server's channel list, searches, posts, hidden listings, cleanup,
  status, listings, rules, replays, versions, history imports and post
  removals. A change to a channel also needs Manage Channels in that channel,
  counting its overwrites, as the slash commands check it.
- **Member:** everyone else in the server, and a member in timeout even when
  their roles would make them a manager. You see and remove only your own 🔔
  notifications there. Every other page and API route about the server answers
  exactly like a server that does not exist. Someone who manages no server at
  all gets 404 from every route except their session, the server list and their
  own notifications, so they cannot use the rule checker or the replay worker
  either.

A search or channel in a server you are not in answers like one that does not
exist too. Someone who is only a member somewhere starts on their notifications.
Your notifications show where each listing was posted only for channels you can
view now, counting the channel's overwrites. A listing posted only in channels
you cannot view, or in servers you left, is listed without its title, price or
photo, so you can still stop following it.

Discord's access token is used once, to read your ID, name and avatar, and is
then revoked at Discord. The dashboard does not store it and does not use it to
list your servers. Discord shows its consent screen at every sign-in: Discord
does not document what skipping it does for someone who never approved the
app, so the dashboard does not ask to skip it. The sign-in uses a `state` value tied to a short-lived cookie, plus
PKCE. Discord's OAuth2 page does not describe PKCE, but Discord accepts it; the
`state` check protects the sign-in either way.

The bot checks your servers again after 5 minutes, on your next request. If
you gained or lost Manage Channels in a server, you become its manager or a
member there (logged as `dashboard_access_changed`). If you left a server, it
disappears. If you are in none of the bot's servers any more, you are signed
out and the sign-in page says why. If Discord
does not answer, the dashboard refuses requests with "can't reach Discord" and
asks again after 30 seconds; it does not fall back on the earlier answer.

Sign-in is refused, with a message on the sign-in page and a
`dashboard_login_denied` log line with the reason, when you are in none of the
bot's servers, cancel on Discord, or the sign-in expired or was started in
another browser. A sign-in attempt is valid
for 10 minutes, only in the browser that started it, and its cookie is removed
when Discord sends the person back. The dashboard keeps nothing on the server for
a sign-in in progress: the `state` carries when it started and a signature
over that time and the browser's login cookie, made with a key that is new at
every start of the bot. So starting many sign-ins cannot push out anyone
else's, and a restart only cancels sign-ins that were in progress.

#### Cookies

Discord sends the browser back from discord.com, another site. Browsers leave
out SameSite=Strict cookies on that request, and on any redirect that follows
it. So the sign-in uses a second cookie, `dashboard_login`, which is
SameSite=Lax, lives 10 minutes and is only sent to `/auth/discord`. When
Discord sends you back, the dashboard sets the usual Strict session cookie and
answers with a small page that moves on to `/auth/discord/finish` by itself.
That request comes from the dashboard's own page, so the browser sends the Strict
cookie, and `/auth/discord/finish` checks that it arrived before showing the
UI. If a browser blocks the cookie, the sign-in page says so.

#### Set it up

1. In the [Discord Developer Portal](https://discord.com/developers/applications),
   open the bot's application. For the dev bot that is PosterFinderDev.
2. Under **OAuth2**, **Redirects**, add the address the dashboard is opened at
   followed by `/auth/discord/callback`. For the dev instance that is
   `https://yahoo-dev.waxdt.com/auth/discord/callback`. It must match
   exactly: https, no trailing slash.
3. Under **OAuth2**, **Client Secret**, reset the secret if it is not shown and
   copy it. The client ID is the application ID; the dashboard reads it from
   Discord with the bot token, so there is nothing to set for it.
4. Set these in the bot's `.env`, then restart the bot:

   ```bash
   DASHBOARD_PUBLIC_URL=https://yahoo-dev.waxdt.com
   # The secret in a file, which the dev box already has:
   DASHBOARD_DISCORD_CLIENT_SECRET_FILE=/data/discord-client-secret
   # Or the secret itself:
   # DASHBOARD_DISCORD_CLIENT_SECRET=the-client-secret
   # The reverse proxies in front of the dashboard (see below):
   DASHBOARD_TRUSTED_PROXIES=172.18.0.0/16
   ```

   Remove `DASHBOARD_TOKEN` and `DASHBOARD_TOKEN_FILE`. An old
   `alerts.db.dashboard-token` file is no longer used and can be deleted.

The bot needs no new permissions, scopes or privileged intents. Startup stops
with a clear error when the secret is set without `DASHBOARD_PUBLIC_URL` or the
other way round, when the address has a path or uses plain http (only
`localhost` may use http), when both the secret and the secret file are set,
when the access-key settings are still set, or when `BOT_TOKEN` is missing.
The secret is removed from log output if it ever appears there.

Behind a reverse proxy, keep the browser's Host header, send
`X-Forwarded-Proto: https`, and list the proxy in `DASHBOARD_TRUSTED_PROXIES`
(see [Behind a reverse proxy or Cloudflare](#behind-a-reverse-proxy-or-cloudflare)).
Without that header the sign-in button answers with an error that names it,
instead of sending the browser in circles. When someone opens
the dashboard at another address, such as an SSH tunnel, the sign-in button first
moves them to `DASHBOARD_PUBLIC_URL`, because Discord only returns to that
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
`<DATABASE_URL>.dashboard-token`, for example `alerts.db.dashboard-token`. Read that
file locally and paste the key into the sign-in form. The file has mode `0600`;
the key is never placed in a URL, browser storage, or application logs. Set
`DASHBOARD_TOKEN` to provide your own key of at least 16 characters, or
`DASHBOARD_TOKEN_FILE` to choose another private file location. The access key
sees every server, including searches without one.

### Running the dashboard

To open an existing database without starting the Discord gateway, polling or
delivery workers:

```bash
python dashboard.py --database alerts.db
```

The command refuses a missing database unless `--init` is explicitly supplied.
It performs the same backed-up migrations as the bot. Run one application
process per database; use the bot's embedded listener when the bot is already
running. With Discord sign-in set up, this mode checks servers through
Discord's REST API with `BOT_TOKEN`, without the gateway.

The UI is a React app in `frontend/`. The Docker image builds it, so a container
needs nothing extra. When the bot or `dashboard.py` runs from a checkout, build the
UI once first (see [Developing the UI](#developing-the-ui)). Until then the page
says how to build it.

Sessions use an HttpOnly, SameSite Strict cookie and expire after 12 hours; at
most 128 are kept, and at most 5 per Discord user, so one person cannot push
everyone else out. Mutations require same-origin JSON requests.

Failed sign-ins are counted per visitor: one IPv4 address, or one IPv6 /64
(people usually get a whole /64). After 10 failures in a minute, that visitor's
sign-ins are refused for the rest of the minute; everyone else can still sign
in. Wrong access keys count, and so do Discord sign-ins that Discord sent back
and that then failed, such as a cancel. A broken or foreign sign-in link does
not count, because another site could send someone's browser to one to lock
them out. On top of that, failures that cost Discord API calls (a code Discord
did not accept, a membership check that found nothing, Discord not answering)
are counted for everyone together: after 60 in a minute, new sign-ins wait for
the rest of the minute before Discord is asked again. The bot shares its
address with the production bot, and Discord blocks addresses that make many failing
calls. Cancels and broken links never count for everyone. At most 4,096
visitors are remembered; the one whose last failure is oldest goes first.

The
bot serves the UI's files itself; nothing loads from a CDN. The page's content
security policy allows only those files, plus style tags that carry a new
random value (a nonce) on every page view. Discord avatars and server icons
load from Discord's image server. The default listener binds to loopback. For
remote operation, use an SSH tunnel or a private HTTPS reverse proxy; preserve
the browser's Host and Origin. Cookies are marked Secure when the request
reaching the application uses HTTPS.

### Logs

Sign-in logs `dashboard_login_succeeded` and `dashboard_login_denied` with the
method, the reason and the Discord user ID when it is known.
`dashboard_access_revoked` names the servers someone left,
`dashboard_access_changed` the servers where someone became a manager or a
member, and `dashboard_access_check_failed` says Discord did not answer a check.

Every change logs `actor_id`, the Discord user ID, and `sign_in` (`discord` or
`access_key`). Publishing, restoring and history imports log
`review_rules_published`, `review_rules_restored` and `review_history_imported`. Changes that a slash command or reaction can also
make log the same event as the command, with `via` set to `dashboard`:
`alert_registered`, `alert_unregistered`, `filter_deleted`, `item_blacklisted`
(hiding), `cleanup_completed`, `cleanup_reactions_completed`,
`notification_subscribed` and `notification_unsubscribed`. Showing a listing
again logs `item_unhidden`, and queued post removals log `post_removal_queued`
with `reason` `rules` or `cleanup`. Codes, tokens, the PKCE verifier and the
client secret are never logged.

## Servers and channels

The dashboard looks like Discord. The server list is on the far left, the picked
server's channels next to it, and the page on the right. On a phone, the menu
button or a swipe to the right opens both lists; see [On a phone](#on-a-phone).
The round button at the top of the server list is Home: your 🔔 notifications, or
every server's searches with the access key. Settings, under your name at the
bottom, has the appearance: light, dark or the same as the system, in Discord's
own colours.

The channel list starts with three pages of the whole server: **Status**,
**Searches** (every search, as `/allalerts` lists them) and **All listings**.
Below them are the server's channels in Discord's order: channels without a
category first, then each category by its position, and inside each one the
text and announcement channels before the voice channels. A channel's searches
are listed under it, and so are its threads that have searches or hidden
listings. The badge counts the channel's searches. A warning sign marks a
channel where the bot lacks a permission it needs to post; it is red when the
channel has searches that cannot post. **Unknown channels** at the bottom are
channels with searches or hidden listings that are not in the server's list:
*deleted* when Discord says the channel no longer exists, *unknown* when the
bot may not see it or Discord did not answer.

In a server where you are only a member, the channel list has just your
notifications there.

### On a phone

On a phone or a small tablet the dashboard works like Discord's app. Swipe to
the right anywhere on a page, or tap the menu button, to open the server and
channel lists. A search's tabs and a channel's tabs sit in a bar at the bottom
of the screen, and tapping a search's name at the top shows its counts and
**Unregister**. Dialogs open as sheets from the bottom of the screen; drag a
sheet down to close it.

Press and hold a listing for what you can do with it: its details, the
marketplace page, testing its title, 🔔 and copying its link. A tap opens the
details, where a swipe to the left or right moves to the next or previous
listing and a swipe down closes them. Posts, hidden listings, searches, rule
versions and your notifications work the same way: press and hold one, or tap
its ⋯ button, for its actions.

Buttons and rows are big enough for a finger, and text fields use 16 pixel text,
so iOS does not zoom in while you type.

### Where the channel list comes from

Inside the bot, channels, threads, roles and the bot's own roles come from the
gateway cache, which Discord keeps current. The standalone `dashboard.py` asks
Discord's REST API with `BOT_TOKEN` instead, and keeps each server's answer for
60 seconds. The bot does the same for a server that is not in its cache yet:
right after connecting, Discord sends each server's channels a few seconds
after the bot is ready. A channel only counts as deleted when Discord answers
that it does not exist; one that is missing from the cache is looked up first.
Without a bot token, the dashboard knows channels only by their ID and cannot
change anything in them.

The bot needs these permissions to post a search's listings: View Channel, Send
Messages (Send Messages in Threads in a thread), Embed Links, Add Reactions and
Read Message History. Discord wants Read Message History before it lets the bot
add the 🗑️ and 🔔 reactions. With Manage Messages too, the bot removes recent
posts 100 at a time instead of one by one. The dashboard works these out the way
Discord does: the bot's roles, then the channel's overwrites for @everyone, for
its roles together and for the bot itself. Administrator allows everything, and
without View Channel nothing else counts. A thread uses its parent channel's
overwrites; a locked thread takes no posts, and the bot must be added to a
private thread. The same code works out whether you have Manage Channels in a
channel, and whether you can view a channel for your notifications.

### Searches

**Add search**, on the Searches page or in a channel's Searches tab, does what
`/register` does. The query takes 1 to 100 characters and the spaces at its ends
are dropped, with the same check as the slash command. The channel must be a
text channel, an announcement channel or a thread where the bot can post, and
you need Manage Channels in it. The dashboard looks the channel up with Discord
and takes its server from Discord's answer, never from the browser.

**Unregister** does what `/unregister` does, after saying what happens: the bot
stops checking the search, its posts stay in Discord (the channel's Cleanup tab
removes them), posts not sent yet are cancelled, its rule versions and saved
listings are kept without the search, and its Discord filters are deleted.
Hidden listings and 🔔 follows do not change. A search whose channel Discord
says is deleted can be unregistered too.

### A channel's pages

- **Searches** lists the channel's searches, as `/alerts` does.
- **Posts** lists the bot's live posts, newest first. **Follow** does what 🔔
  does: you get a DM when the listing changes. The count next to 🔔 says how many
  people follow it; who they are is never shown. **Hide** does what 🗑️ does: the
  listing is not posted in the channel again, and its posts there are removed,
  also when someone follows it. Followers keep getting their DMs.
- **Hidden** lists the listings hidden in the channel. **Show again** removes the
  hide. The listing is not posted again right away; its next change is.
- **Cleanup** has two parts. **Remove posts** removes the channel's tracked posts
  of the last 7, 30 or 90 days, or all of them, for one search or every search,
  through the same queue as removing the posts that rules filter: newest first,
  up to 100 per request when they are under 14 days old. Posts that someone
  follows with 🔔 are kept, and nothing is hidden. **Scan recent messages** does
  what `/cleanup` and `/reacttocleanup` do with the channel's latest 1,000
  messages: delete up to 100 of the bot's posts, or add 🗑️ to the tracked ones.
  It reaches posts the bot does not track, such as posts from before the
  database was converted. It needs the bot running and connected, and it runs in
  the background while the page shows how far it got.

A channel that Discord says is deleted has only the Searches and Hidden tabs, to
unregister its searches and clear its hidden listings.

### Your notifications

Home lists the listings you follow with 🔔, from every server of the bot you
are in. Each one says where it was posted, but only for channels you can view
now; one that is only in channels you cannot view, or in servers you left, is
listed without its title, price and photo. **Following** stops the DMs for any
of them. Nobody else's follows are listed. With the access key there is no
Discord user, so there are no notifications.

### Status

The Status page shows, for the server, whether the bot is ready and connected,
when the last round of checks ended and the next one starts, and the last
round without errors for each marketplace. For each search it shows the last
check for each marketplace: whether it worked, timed out or failed and with
which kind of error, its listings, and its posts and DMs waiting to be sent or
failed. The checks are kept in memory, so after a restart a search shows "not
checked since the bot started" until its next check. The standalone
`dashboard.py` does not run the checks, so it shows only the counts from the
database. The server list puts a red dot on a server where a search failed its
last check or a post or DM could not be sent.

Each card and the Searches table have a **?** that explains them. Below them,
**Graphs** shows the main graphs of the bot's Grafana dashboard for the last
hour, 6 hours, 24 hours or 7 days: checks and how long ago each marketplace
last worked, how long rounds take, each search's checks and check time,
listings, marketplace requests, and Discord delivery and the outbox. Each
graph's **?** gives the same explanation Grafana shows. Graphs marked **This
server** only count this server's searches; **All servers** graphs count the
whole bot. A search's name in a table opens its page. The graphs come from the
Prometheus that scrapes the bot, so they need `PROMETHEUS_URL`, and
`PROMETHEUS_INSTANCE` when more than one bot reports to it; see
[monitoring.md](monitoring.md#the-same-graphs-on-the-dashboards-status-page).
The standalone `dashboard.py` shows them too.

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

Existing Discord filters, made with `/filters add`, are listed at the end of the
Rules tab with their value, whether they block or allow, text or regex, whether
they are enabled, and how often they matched, as `/filters get` shows them. The
delete button does what `/filters delete` does. New filters are made as rule
groups instead; the dashboard does not add Discord filters. Their original
case-sensitive text and raw regex behavior is preserved. **Include existing
filters** controls whether they apply alongside the profile. A legacy blacklist
remains a veto, and enabled legacy whitelist terms still combine with OR.
Filters converted from the old database lost whether they were text or a regex,
so they stay disabled; to keep one, add its term to a group and delete the old
filter. Changing those filters in Discord affects future checks and replay
using the current legacy filters; their historical state is not reconstructed
by replay.

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
it. When someone else signs in on the same browser, the earlier person's drafts
are removed. If someone publishes while you edit, the draft says it was based on an older
version: keep it on top of the new version, or discard it.

Use **Test a title** (`t`) for a specific example. Run replay to compare the
published rules with your draft on saved listings. Each row shows the recorded
original decision, the published rules' result and the draft result. The
summary counts the listings the draft newly allows or newly blocks. These
counts cover the saved sample, not all marketplace traffic.

Replay uses the latest decision of the `DASHBOARD_REPLAY_LIMIT` most recently
seen listings (default and maximum 500). Processing has a 10-second budget, and
the result says when it is partial. Replay does not poll
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
later price or stock change would post an update. When the dashboard runs without
the bot (`dashboard.py`), removals wait in the queue until the bot runs. Removed
posts cannot be brought back; the listings in the dashboard stay. With
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
archives the same way. Schema version 5 deletes the listing labels that earlier
versions saved, because the dashboard no longer uses them; its migration backs
up the database first too.

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

Configuration is listed in [.env.example](../.env.example): `DASHBOARD_ENABLED`,
`DASHBOARD_HOST`, `DASHBOARD_PORT`, `DASHBOARD_PUBLIC_URL`, `DASHBOARD_DISCORD_CLIENT_SECRET`,
`DASHBOARD_DISCORD_CLIENT_SECRET_FILE`, `DASHBOARD_TOKEN`, `DASHBOARD_TOKEN_FILE`,
`DASHBOARD_TRUSTED_PROXIES`, `DASHBOARD_REPLAY_LIMIT`, `HISTORY_RETENTION_DAYS` and
`HISTORY_MAX_ROWS`.

These settings were called `REVIEW_*` before, for example `REVIEW_PORT`. The bot
and `dashboard.py` refuse to start while an old name is set, even to an empty
value, and the error lists the new name for each one.

For a local Docker deployment, add `-e DASHBOARD_HOST=0.0.0.0` and
`-p 127.0.0.1:9101:9101` to the README's container command. This maps the UI to
the host's loopback interface. Without Discord sign-in and with
`DATABASE_URL=/data/alerts.db`, the generated key is
`data/alerts.db.dashboard-token` on the host's mounted data directory.

### Behind a reverse proxy or Cloudflare

Behind a proxy, every request reaches the dashboard from the proxy's address,
and the browser's own address and scheme come in headers the proxy adds. A
visitor can send those headers too, so the dashboard only believes them from
the proxies listed in `DASHBOARD_TRUSTED_PROXIES`: comma-separated addresses or
CIDR ranges, such as `172.18.0.0/16` for a Docker network. It is empty by
default, which trusts nobody. Startup refuses an entry that is not an address or
range, and logs the trusted ranges in `dashboard_started`.

- **Who the visitor is.** From a trusted proxy, the visitor is the rightmost
  `X-Forwarded-For` entry that is not itself a trusted proxy. Each proxy adds
  the address it got the request from at the end, so entries further left could
  have been written by the visitor. From anyone else, the visitor is the
  connection's own address, whatever `X-Forwarded-For` says.
- **Whether the browser used https.** `X-Forwarded-Proto` counts only from a
  trusted proxy. The dashboard uses it for the same-origin check and to mark
  cookies Secure.

The dev instance has two routes in. The public one is Cloudflare, then nginx
(`web-nginx-1`), then the container on port 9101. nginx sets `X-Real-IP`,
replaces `X-Forwarded-For` with the visitor's address from `CF-Connecting-IP`,
and sends `X-Forwarded-Proto: https` with the original Host. The internal
host `yahoo.internal.waxdt.com` goes through traefik, which adds to
`X-Forwarded-For`. Both proxies are on the same Docker network, so that network
is the one value for `DASHBOARD_TRUSTED_PROXIES`. Cloudflare's own addresses do
not go in it: nginx already replaced the header with the visitor Cloudflare
reported.

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

`GET /api/session` says whether the browser is signed in and which sign-in this
dashboard uses (`method` is `discord` or `access_key`), with the page's `title`
and the `bot`. With Discord it also returns the `user` and the `guilds`
(servers) the person is in, each with its `level`: `manager` or `member`. With
Discord sign-in, `guild_id` on `/api/candidates` limits All listings to one of
the servers they manage, and `/api/alerts` totals list each server under
`guilds`.

The management routes:

| Route | What it does |
|---|---|
| `GET /api/guilds` | The server list, with counts and problems for the servers you manage |
| `GET /api/guilds/{id}/channels` | The channel list in Discord's order, with each channel's searches, hidden listings and the bot's permissions |
| `GET /api/guilds/{id}/status` | The bot's state and each search's last checks and waiting posts |
| `GET /api/guilds/{id}/graphs` | The Status page's graphs; `range` is `1h`, `6h`, `24h` (the default) or `7d` |
| `POST /api/alerts` | `/register`: `channel_id` and `search_query` |
| `GET` and `DELETE /api/alerts/{id}` | A search with what unregistering touches; `/unregister` |
| `DELETE /api/alerts/{id}/legacy-filters/{filter}` | `/filters delete` |
| `GET /api/channels/{id}/posts` | The bot's live posts, 50 a page; `before` is the last `message_id` of the page before |
| `GET /api/channels/{id}/hidden`, `PUT` and `DELETE .../hidden/{item}` | Hidden listings; hide, as 🗑️; show again |
| `POST .../posts/removal-preview`, `POST` and `GET .../posts/removal` | The channel's cleanup: which posts, queue them, progress |
| `POST` and `GET /api/channels/{id}/history-scan` | `/cleanup` (`delete_bot_posts`, with `count`) or `/reacttocleanup` (`add_reactions`) |
| `GET /api/me/notifications`, `PUT` and `DELETE .../{item}` | Your own follows; follow, as 🔔; stop |

The graphs answer `enabled: false` without `PROMETHEUS_URL`. Otherwise
`times` lists the Unix times that every series' `values` belong to, where
`null` is a gap. A panel whose query failed has an `error` and no data, and
`warning` explains a problem that affects every panel.

Every route only reaches the servers you manage, except your own notifications.
A search, channel or server elsewhere answers exactly like one that does not
exist. A change answers 403 without Manage Channels in the channel, 409 when it
cannot be done there (such as a deleted channel, or a history scan without the
bot), and 503 `discord_unavailable` when Discord did not answer the channel
lookup. A request
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

For live reloading, run the dashboard on its usual port and start Vite next
to it. Vite serves the UI on http://127.0.0.1:5173 and forwards `/api` to
`http://127.0.0.1:9101`, or to `DASHBOARD_BACKEND` when set.

```bash
python dashboard.py --database alerts.db &
cd frontend && npm run dev
```

The Vite server sends no content security policy, so check style and nonce
changes against the built UI served by `dashboard.py`. Before pushing, run the
same checks as CI:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

### Trying Discord sign-in

`devtools/dashboard_harness.py` runs the dashboard with Discord sign-in against a
small fake Discord on this computer, so no Discord application is needed. Use a
copy of a database, never the bot's own file:

```bash
cp alerts.db dashboard-scratch.db
python -m devtools.dashboard_harness --database dashboard-scratch.db --recheck 20
```

Open http://127.0.0.1:9101. The fake Discord runs at http://localhost:9199,
which the browser treats as another site, like discord.com. Its sign-in page
offers five people: alice manages the first server, erin manages every server,
bob is a member without Manage Channels (so he sees only his notifications),
carol is in no server, and dave owns the last server.
http://localhost:9199/fake removes members, changes roles, deletes channels and
can make Discord stop answering. `--recheck` shortens the 5 minutes between
access checks. The servers come from the alerts in the database, plus one more
without searches. Each gets channels like a small server: a welcome channel,
the searches' channels under a category with two threads (one archived), and a
category with a channel only managers can view, one where managers may not
change things, one where the bot cannot add reactions, an announcement channel
and a voice channel. The tests use the same fake (`devtools/fake_discord.py`),
so nothing in them reaches Discord.

