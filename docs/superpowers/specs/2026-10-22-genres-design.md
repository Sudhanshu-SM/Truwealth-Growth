# Genres: pick what you post about, see what's trending there

Date: 2026-10-22. Status: proposed, waiting for the user's go-ahead.

## Intent

The user asked for this on 2026-10-21, in their words:

> "don't keep it finance specific, ask users what genre of posts they want while onboarding (they can change later in
> settings) Give them a lot of options from which they can select multiple. Once the user selects, show them the
> trending from that particular genres and also show the genre in the card on which the topic is shown so that user
> knows which genre it is when they have selected multiple and also show multiple genre names if applicable, even if
> user has selected only one of them"

On 2026-10-22 they opened Studio, were not asked for genres, and found Trending empty. Trending being empty is a
separate fix (the radar never wrote to Supabase; Truwealth-Growth PR #3). This document covers the genres.

Why: Studio now gives anyone Google lets in (@truwealth.club) their own private space. Not everyone posts about
money. Each person should see trending topics in their own areas.

## Goals

1. **Ask once.** After signing in, anyone who has not picked genres yet sees a "What do you post about?" screen
   before anything else, with the genres below as chips. They pick one or more and continue. This includes people
   who already use Studio (the user and Tejas), not only new sign-ups.
2. **Change any time.** Settings has a "Your genres" card with the same chips.
3. **Trending follows the genres.** Trending shows a radar topic only when it shares at least one genre with the
   person. "Your topics" (their own manual topics) is not filtered.
4. **Cards name their genres.** Every Trending card shows all of its topic's genre names, including genres the
   person did not pick.
5. **The radar finds trends in every genre**, not only finance.
6. **No genre sits empty.** Every genre gets at least one topic every 12 hours (see "Quiet genres").

## Non-goals

- No AI in the radar. It stays rule-based (keywords, news searches, spike detection), free and without new keys.
  Its original spec ruled out LLM text. (Claude's call.)
- No change to what Tejas's live ghostwriter receives: the Google Sheet's Radar topics tab and the HOT emails keep
  getting finance topics only, with today's caps.
- No change to how the writer writes (prompts, voice). See "Open follow-ups".
- No genre filter chips inside Trending; the person's own genres already filter it. (Claude's call.)
- No new YouTube channels or subreddits for the new genres for now: news searches plus Google and X trends only.
  (Claude's call.)
- No catch-all "General & viral" genre. A trend the radar can't place in a genre is not handed off. Raw X and Google
  trends are full of birthday and political hashtags, and the writer's hot lane would auto-draft them. (Claude's
  call, after the builder check.)

## Anti-goals (a failure even if everything else works)

- A non-finance topic reaches Tejas's Sheet. His live engine auto-drafts radar topics from the Sheet (hot topics at
  once, rising ones into open posting slots), and in autopilot it posts them. A cricket topic there would become a
  cricket post on his LinkedIn.
- The Supabase engine auto-drafts a radar topic that shares no genre with that person.
- Someone picks a genre and their Trending stays empty for days.

## The genres

28 genres in six groups. Ids are stable; names are what people see.

| Group | id: name |
| --- | --- |
| Money & work | `personal_finance`: Personal finance · `stock_market`: Stock market & trading · `economy`: Economy & policy · `wealth`: Wealth & investing · `crypto`: Crypto · `real_estate`: Real estate · `business`: Startups & business · `careers`: Careers & jobs · `marketing`: Marketing & creators |
| Tech & science | `technology`: Tech & gadgets · `ai`: AI · `science`: Science & space |
| Sports | `cricket`: Cricket · `football`: Football · `sports`: Other sports |
| Entertainment | `movies`: Movies & Bollywood · `ott_tv`: OTT & TV · `music`: Music · `gaming`: Gaming |
| Lifestyle | `health`: Health & fitness · `food`: Food · `travel`: Travel · `fashion`: Fashion & beauty · `auto`: Cars & bikes · `spirituality`: Spirituality & astrology |
| Society | `politics`: Politics & current affairs · `education`: Education & exams · `environment`: Environment & weather |

**Finance genres:** `personal_finance`, `stock_market`, `economy`, `wealth`, `crypto`. A topic with at least one of
these is a finance topic. Only finance topics go to the Sheet and the HOT emails.

## How it works

### Radar (repo Truwealth-Growth, `F:\Truwealth`)

- **Genre list:** in config (id, name, group, whether it's a finance genre). Config loading rejects a topic or source
  that names an unknown genre.
- **Static topics:** every topic in `config/topics.yaml` gets `genres` (one or more). Each of today's 51 finance
  topics keeps at least one finance genre and may add others (home buying is also `real_estate`; salary is also
  `careers`). Every non-finance genre gets its own handful of static topics with keywords.
- **Sources:** each non-finance genre gets Google News searches (Indian outlets, like today's finance searches),
  tagged with that genre. Today's finance feeds and searches are tagged with finance genres. An item's genres come
  from the source it came from plus the static topics it matches. Google and X trend items carry no genre of their
  own; they still add heat to the static topics they match, as today.
- **Emerging topics** (new-phrase spikes): today a phrase must be mostly finance to count. That becomes "mostly
  items that have a genre". An emerging topic's genres are the genres common among its items, at most three. A
  phrase with no genre evidence (one born only from Google or X trends) is not a topic.
- **Handoff:** every handed-off row carries its `genres` (ordered, most relevant first).
  - Supabase gets every genre. Each topic goes at most once per 24 hours (as today). A per-genre daily cap, counted
    on the topic's first genre, stops one busy genre from crowding out the rest.
  - The Sheet gets finance topics only, with today's caps (10 rising a day).
  - HOT alerts (emails, daily cap 4) consider finance topics only, as today. A non-finance topic above the HOT
    threshold goes to Supabase with kind `hot`, without an email.
- **Quiet genres:** a topic is normally handed off only when it spikes, and the radar runs only about five times a
  day. Steady genres (food, fashion, spirituality, education) would often show nothing. So each run, any genre that
  has had nothing handed off to Supabase for 12 hours gets its biggest recent story handed off with kind `latest`:
  the topic in that genre with the most news items in the last 24 hours, if it has any. One per genre per 12 hours.
  Supabase only, never the Sheet.

### Supabase (`supabase/migrations/` in the Ghostwriter repo)

- New migration: `radar_topics.genres text[] not null default '{}'`. Rows already there are backfilled from their
  `bucket` (personal_finance → `personal_finance`, markets → `economy`, wealth → `wealth`, trading →
  `stock_market`, anything else → `economy`). `radar_feed` and `radar_feed_for` return `genres` too. `kind` gains
  the value `latest`.
- A person's genres live in their `settings` rows under key `genres`, as comma-separated ids. No row (or an empty
  one) means "not picked yet". No schema change for this part.

### Studio (`web/`)

- **Genre screen:** after sign-in, before Posts, when the person has no genres. Title "What do you post about?",
  one line saying they can pick several and change them later in Settings. Chips grouped as in the table. Continue
  stays disabled until at least one is picked; it saves and opens Posts.
- **Settings card "Your genres":** the same chips. Each tap saves at once (like Posting slots). The last selected
  genre can't be turned off.
- **Trending:** only topics sharing a genre with the person. Each card shows its genre names as small chips: the
  person's own genres first, then the rest. (Order is Claude's call.) Kind `latest` shows a plain "Latest" badge
  next to today's "Hot" and "Rising". The empty state says nothing is trending in their genres right now and offers
  a "Change genres" button that opens Settings.
- The local stand-in (`dev-supabase.js`) seeds topics with genres so all of this works without the live project.

### Writer engine (`ghost/`, the Supabase port)

- The hot lane and the slot lane only take radar topics that share a genre with the person. A person with no
  genres set gets the finance genres, which is today's behaviour. The slot lane treats `latest` like `rising`; the
  hot lane takes only `hot` and `capped`, as today.

## Constraints

- Two repos: the radar is `F:\Truwealth` (Truwealth-Growth), Studio, schema and engine are
  `F:\Truwealth-Ghostwriter` (branch `feat/studio-web`, which holds much uncommitted work from other sessions).
- Other sessions edit `web/index.html`, `web/data.js`, `app/src/core` and migrations. Check none is mid-edit before
  touching those files. Nothing in the Ghostwriter repo is committed until the user says so.
- Migrations are new files with unique version numbers, never edits to applied ones. They are applied to the live
  project only after the user says yes, through Claude in Chrome (never the connected Supabase MCP).
- $0: free sources only, no paid APIs, no new keys.
- The radar change needs PR #3 (radar → Supabase) merged first.

## Left to the builder

- Keywords for each new static topic, the exact Google News search strings, and how many topics per genre.
- The per-genre daily cap number and the share of items that makes a genre "common" in an emerging topic.
- Chip styling and the exact words on the genre screen, within the goals above.
- A dry-run check of how many topics each genre gets per day, before going live.
- Test layout, following each repo's existing tests.

## Open follow-ups (not in this build)

- The writer's prompts describe the founder of a financial advisory firm. A person who picks cricket gets cricket
  topics written in that frame. Each person's own voice and About facts may be enough. If not, the prompts need a
  per-person framing.
- YouTube channels and subreddits per genre, if news searches alone feel thin for some genres.
