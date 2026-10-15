# Filter Lab

Filter Lab is the bot's operator UI for examining candidate listings and testing
rules against saved marketplace facts. Open http://127.0.0.1:9101 while the bot
is running. The listener is separate from Prometheus on port 9100.

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

The key grants operator access to every alert and archived record. Sessions use
an HttpOnly, SameSite Strict cookie and expire after 12 hours. Mutations require
same-origin JSON requests, and failed logins are rate limited. The UI loads its
assets locally without a build step or CDN. The default listener binds to
loopback. For remote operation, use an SSH tunnel or a private HTTPS reverse
proxy; preserve the browser's Host and Origin. Cookies are marked Secure when
the request reaching the application uses HTTPS. Multi-user roles and Discord
OAuth are future extensions, not part of this operator interface.

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

## Browse, label and replay

Select an alert, inspect the original and normalized titles, and label examples
as relevant, wrong product, accessory, bundle or unsure. Labels are for measuring
draft quality; they do not change the live rules automatically. History can be
searched and filtered by source, decision and feedback.

Use title preview for a specific example. Run replay to compare the active
profile with your draft on recent snapshots. Each row shows the recorded
original decision, today's active-profile result and the draft result. Summary
counts include newly allowed/blocked listings, unwanted examples still allowed,
and relevant examples blocked. These counts measure the labeled sample, not all
marketplace traffic.

Replay examines at most `REVIEW_REPLAY_LIMIT` snapshots (default and maximum 500)
with a 10-second processing budget, and reports when the result is partial.
It does not poll marketplaces, change listing baselines, queue notifications or
simulate old delivery timelines. Recorded channel-blacklist vetoes remain
blocked in both comparisons; changing blacklist state, subscriptions and stock
changes are outside this eligibility comparison. Invalid, unenriched or
truncated listing snapshots stay in review rather than being treated as fully
known facts.

Publish creates an immutable version after checking that the active version
has not changed since you loaded it. If another operator publishes first,
reload and compare before retrying. Restore creates a new version from an older
profile. A check already in progress finishes with the profile it captured;
the next check uses the newly published profile. Publication does not resend
historical listings, cancel already queued notifications or reset baselines.

## History and storage

New polling saves accepted, filtered, review, blacklisted, invalid and enrichment
failure candidates. Accepted candidate history commits in the same transaction
as listing facts, per-alert baselines and delivery jobs. Rejected candidates
create history only. Repeated polls can produce repeated snapshots; the archive
represents observations rather than unique products.

The **Import saved history** action explicitly imports up to 1,000 recent
available delivery/listing snapshots. Stable import keys prevent duplicate
imports. Older records lack their original eligibility decision and are marked
incomplete. Previously rejected listings were never saved by the old pipeline
and cannot be recovered. Import does not send notifications.

Defaults retain 90 days of candidates with a target maximum of 50,000 rows.
The bot's statistics worker prunes at most 1,000 rows per pass, once per minute
when caught up, or on successive statistics ticks while a backlog remains.
The limit is a retention target; catch-up is bounded and can lag sustained heavy
capture. Feedback is removed
with its candidate. Standalone UI mode does not run this background pruning.
Rule-version history is retained independently. Existing delivery and reaction
history retains its previous behavior.

Configuration is listed in [.env.example](../.env.example): `REVIEW_ENABLED`,
`REVIEW_HOST`, `REVIEW_PORT`, `REVIEW_TOKEN`, `REVIEW_TOKEN_FILE`,
`REVIEW_REPLAY_LIMIT`, `HISTORY_RETENTION_DAYS` and `HISTORY_MAX_ROWS`.

For a local Docker deployment, add `-e REVIEW_HOST=0.0.0.0` and
`-p 127.0.0.1:9101:9101` to the README's container command. This maps the UI to
the host's loopback interface. With `DATABASE_URL=/data/alerts.db`, the generated
key is `data/alerts.db.review-token` on the host's mounted data directory.
