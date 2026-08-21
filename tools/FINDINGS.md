# LeetCode API findings

Confirmed live against a signed-in session on `weekly-contest-515`, 2026-08-18.
These replace the guesses the initial scaffold was written against.

## Auth

`LEETCODE_SESSION` is **HttpOnly**, so `document.cookie` cannot see it and any
login check based on it reports false negatives. Use instead:

```
POST /graphql/   { query: "{ userStatus { isSignedIn username } }" }
```

Playwright's `context.cookies()` *can* see HttpOnly cookies, but the GraphQL
check is the honest one — it confirms the session is actually valid, not merely
that a cookie exists.

## Ranking — two regions, two different payloads

Both are needed; `core/contest.py` merges them per page (25 rows per page).

### `region=global`

```
GET /contest/api/ranking/{slug}/?pagination={n}&region=global
{ time, is_past, questions[], total_rank[], submissions[], user_num }
```

- `questions[]` -> `{id, question_id, title, title_slug, credit, category_slug}`
- `submissions[i]` is a dict keyed by **question_id**:
  `{id, submission_id, question_id, date, status, lang, fail_count, contest_id, data_region}`
- **`id`** is the *contest submission id* the report endpoint keys on.
  **`submission_id`** is the global submission id used to fetch code.
  They are different numbers and are easy to confuse.
- An upcoming/unrun contest returns `{}`.

### `region=global_v2`

```
GET /contest/api/ranking/{slug}/?pagination={n}&region=global_v2
{ user_num, ak_info, total_rank[] }
```

Rows nest their own data:

- `row.replays` -> `{question_id: true}`, replay availability only (no events)
- `row.submissions[question_id]` ->
  `{submission_id, date, lang, fail_count, not_enough_activities}`

**`not_enough_activities`** is the important one — LeetCode's own
"editor activity status" flag, i.e. their own paste detector. It is `true` or
`null`. On weekly-contest-515 it was `true` for **51 of 400** submissions across
the top 100 (12.75%), and it corresponds exactly to the alternate (magnifier)
icon shown in the ranking table instead of the plain play icon.

## My own placing

```
GET /contest/api/myranking/{slug}/?region=global_v2
{ my_rank: {rank, score, finish_time, user_slug, replays, ...} | null,
  my_solved, my_submission, registered }
```

Found by watching what the ranking page fetches. `my_rank` is `null` for a
contest the signed-in user did not take part in, so its presence is the
participation check too.

Two nearby things that look like they would work and do not:

- The board renders your own row as the literal text **"You"**, with no
  `/u/{username}/` link, so scraping the page for your username never finds
  you however many pages you read.
- GraphQL `userContestRankingHistory` returns the **rated** placing, a
  different number from the board position — 2303 against 2865 on
  weekly-contest-514 — and a contest is absent from it until rating is
  recalculated, which lags the contest by days.

`region=global` and `region=global_v2` can disagree slightly (1482 vs 1471 on
weekly-contest-515). `global_v2` is what the ranking page itself uses.

## Contest timing

```
GET /contest/api/info/{slug}/
-> contest.start_time (epoch seconds), contest.duration (seconds, 5400 for weekly)
```

Solve offset = `submission.date - contest.start_time`.

## Submitted code

```
GET /api/submissions/{submission_id}/
-> { id, lang, code, contest_submission }
```

`contest_submission` is the same id as ranking `global`'s `id`.

## Reports

```
GET /contest/api/reports/submissions/{contest_submission_id}/
```

- Not yet reported -> `{"id": -1}`
- Already reported ->
  `{id, date, username, submission, status, description, user,
    original_submission_id, reported_user, contest_title}`

This is a free "have I already reported this?" check that does not rely on the
local database, and it survives reinstalls.

`description` on an existing report was the canned string
`"Used external AI / unauthorized assistance"`, which suggests the report dialog
offers preset reasons rather than (or in addition to) free text. **The POST/PUT
shape for filing a report was deliberately NOT probed** — sending one would file
a real report against a real person. Confirm it by opening the dialog once by
hand with the network tab open.

## Code Replay events — no API, but scrapable from the player

Opening the Code Replay modal fires only two LeetCode calls:
`/api/submissions/{submission_id}/` and
`/contest/api/reports/submissions/{id}/`. There is **no** request carrying
keystroke events, and no `replay`-named GraphQL operation in the loaded chunks.

So there is no API for the events. **But the player renders them.** Its
"Event History" panel (the list icon in the player footer, i18n key
`toggleEventList`) lists every recorded event, and the DOM is scrapable:

- container: `div.flex.flex-1.flex-col.overflow-y-auto` inside the modal
- one child element per event
- row text: `Type | m:ss | detail` — e.g. `External Paste | 0:06 | size > 500 chars | 🔴`

Event vocabulary, from the i18n bundle key `recordEventType`:

```
start, switchQuestion, switchLang, pageVisible ("Page Switch"),
interpretCode ("Run Code"), submitCode, end, input, undo, redo,
paste ("External Paste"), changeCursor, debug, debugEnd
```

Paste sizes are bucketed (`size > 500 chars`), so treat a size as a lower bound.

This is the detection basis — our own reading of the events — rather than
LeetCode's `not_enough_activities` flag, which misses cases whose own replay
shows a single external paste and no typing.
