# Truwealth Viral Content Radar — Design

- **Date:** 2026-09-26
- **Status:** Design approved in brainstorming; spec pending user review
- **Scope:** v1 suggestion pipeline (detect trending Indian finance topics, email briefs with angles)

## 1. Problem

Truwealth is an Indian financial advisory firm. Its founder wants to post on LinkedIn, X and Instagram about finance topics while they are trending. Finance buzz in India (market moves, RBI/SEBI decisions, tax changes, IPO frenzies, scams) rises and dies within hours, so a suggestion that arrives after the peak is useless.

The radar polls free public signals every 15 minutes, works out which finance topics are spiking, and emails the founder a brief: what is trending, the evidence, how urgent it is, and which content angles fit each platform. It is an in-house tool: its only user is the founder, choosing topics that will gain traction.

## 2. Decisions

| Area | Decision |
|---|---|
| Market | India. English and Hindi signals |
| Founder posts on | LinkedIn, X, Instagram |
| Alerts | Email: instant HOT alert plus a daily digest at 08:00 IST |
| Output | Brief + angles only. No post drafts or scripts in v1 |
| Topics | Personal finance, Markets & macro, Wealth/HNI, Trading & stocks |
| Budget | $0/month |
| X signal | Public trend mirrors only (trends24.in, getdaytrends.com). No X API, no cookie scraping |
| Detection | Fixed topic list plus new-phrase spike detection. No ML models |
| Hosting | GitHub Actions, public repository, every 15 minutes |
| Presentation | No color coding or emoji markers anywhere. All labels are plain text |

## 3. Success criteria

1. **Speed:** a spike visible in the sources produces a HOT email within 30 minutes in the typical case (15-minute cadence plus GitHub schedule delay). Signals only visible on the X mirrors arrive within 75 minutes.
2. **Noise:** at most 4 HOT emails per IST day. A topic alerts at most once per 12 hours unless its heat doubles.
3. **Reliability:** the digest arrives daily; a missing digest means the radar is broken. A failing source never stops a run.
4. **Cost:** $0/month.

## 4. Non-goals (v1)

Post drafts or Reel scripts; LLM-generated text; Instagram or LinkedIn data collection; paid APIs; X cookie scraping; dashboards; auto-posting; engagement feedback loop. Phase 2 candidates are listed in section 15.

## 5. Architecture

```
GitHub Actions, cron every 15 min
  python -m radar run
    1. restore radar.db from the Actions cache
    2. collectors, each isolated          -> list[Signal]
    3. store new items, match to topics (topics.yaml), detect new-phrase spikes
    4. scorer: per-topic values -> heat -> stage -> alert decisions
    5. briefs: evidence + angles
    6. emailer: send HOT emails (or write out/*.html with --dry-run)
    7. prune radar.db, save it back to the cache

GitHub Actions, cron 02:30 UTC (08:00 IST)
  python -m radar digest
```

### Module layout

```
radar/
  __main__.py        CLI: run [--dry-run] | digest [--dry-run]
  config.py          load and validate YAML config
  models.py          Signal, Topic, Angle, TopicScore, Brief dataclasses
  http.py            shared httpx client: 10 s timeout, 1 retry, browser User-Agent
  rss.py             stdlib RSS/Atom parser tolerant of the feeds' date quirks
  text.py            text cleaning, title normalisation, hashing, slugs
  timeutil.py        UTC/IST helpers and date parsing (IST is a fixed UTC+05:30 offset; India has no DST)
  store.py           SQLite schema, shared tables (items, kv, source health), pruning
  collectors/
    __init__.py      Context, run_all (concurrent, isolated), gather (tolerates partial failure)
    google_trends.py
    google_news.py
    news_feeds.py
    regulators.py
    x_trends.py
    youtube.py       channel RSS fetch, plus video storage and outlier scoring
    reddit.py
    markets.py
  events.py          events.yaml -> upcoming events (digest only)
  matcher.py         text -> topic ids
  phrases.py         n-grams, burst detection, emerging topics
  scorer.py          values, baselines, heat, stage, alert decisions
  hooks.py           video title -> angle type; format scoreboard
  briefs.py          assemble Brief objects
  digest.py          assemble the daily digest data
  emailer.py         render (Jinja2) and send (SMTP), or write out/*.html
  pipeline.py        one radar run and the digest, wiring the modules together
  templates/         hot.html, hot.txt, digest.html, digest.txt
config/
  settings.yaml      thresholds, weights, priors, caps, cooldowns
  topics.yaml        47 topics
  angles.yaml        15 angle types
  sources.yaml       feeds, Google News queries, subreddits, tickers and thresholds
  channels.yaml      91 Indian finance YouTube channels
  events.yaml        dated events
tests/
  fixtures/          small RSS/HTML/JSON samples copied from the real formats
  test_*.py
.github/workflows/   radar.yml, digest.yml, ci.yml
requirements.txt     httpx, selectolax, PyYAML, Jinja2
requirements-dev.txt pytest
README.md, .gitignore, .gitattributes, pytest.ini
```

### Unit boundaries

| Unit | Does | Depends on |
|---|---|---|
| collectors/* | Fetch one source, return `list[Signal]` | http, config (run index passed in `ctx`; collectors never touch the database) |
| matcher | Map text to topic ids | topics.yaml |
| phrases | Count phrases, find bursts, create or refresh emerging topics | store, matcher |
| scorer | Compute topic values, heat, stage; decide alerts | store, settings |
| hooks | Classify a title into an angle type | none |
| briefs | Build a Brief for a topic | store, angles.yaml, hooks |
| emailer | Render and deliver HOT and digest emails | templates, SMTP |

Every collector module exposes a pure `parse(raw, ...) -> list[Signal]` function (tested against fixtures) and `collect(ctx) -> list[Signal]`, which fetches and then calls `parse`. `ctx` carries the HTTP client, config, current UTC time and run index. All database writes happen in the main thread after collection, because SQLite connections are not shared across threads.

## 6. Data model

```python
@dataclass
class Signal:
    source: str            # collector id, e.g. "google_news", "trends24", "youtube"
    source_type: str       # news | search_trend | x_trend | video | forum | market | regulator
    feed: str              # outlet/feed id, e.g. "et_markets", "gn:the-economic-times", "r/IndiaInvestments", "yt:<channel id>"
    title: str
    url: str | None
    published_at: datetime | None   # UTC
    text: str = ""         # summary/description used for matching
    lang: str = "en"       # en | hi
    metrics: dict[str, float] = field(default_factory=dict)
    key: str = ""          # natural id from the source: video id, Reddit post id, market event key
    topic_hint: str = ""   # topic the collector already knows (market moves)
```

Metrics by source type: `search_trend` {approx_traffic}; `x_trend` {rank}; `video` {views, is_short, outlier, age_h}; `forum` {rising_rank}; `market` {pct_move, threshold}.

**Item identity:** news items use `sha1("news", normalized title)`. Normalization strips HTML and emoji, lowercases and collapses whitespace, and the Google News collector strips the exact " - <outlet>" suffix, so the same headline from Google News and a direct feed dedupes. Videos use `yt:<video id>`. Google Trends and X trend entries use `sha1(source_type, normalized title)`; their `last_seen_at` shows whether they are still trending. Market events use `sha1("market", symbol:direction:trading date)`, which also enforces one event per symbol, direction and day. Everything else uses `sha1(source_type, key or url or title)`.

### SQLite tables (timestamps are ISO-8601 UTC)

| Table | Purpose | Retention |
|---|---|---|
| `items(id PK, source, source_type, feed, title, url, published_at, first_seen_at, last_seen_at, lang, text, metrics_json)` | Dedupe, evidence links, phrase window | 3 days after last seen |
| `item_topics(item_id, topic_id, PK(item_id, topic_id))` | Item-to-topic mapping | With items |
| `videos(video_id PK, channel_id, channel_name, title, url, published_at, is_short, views, first_seen_at, last_seen_at, outlier, hook_type)` | YouTube videos with latest RSS views; source of creator baselines and the format scoreboard | 30 days |
| `runs(run_at PK, ist_hour)` | Every completed run, for implicit-zero baselines | 8 days |
| `topic_values(run_at, topic_id, source_type, value, PK(run_at, topic_id, source_type))` | Non-zero per-run values | 8 days |
| `topic_heat(run_at, topic_id, heat, stage, n_sources, PK(run_at, topic_id))` | Heat history (rows only when heat > 0) | 8 days |
| `episodes(topic_id PK, started_at, below_watch_runs)` | Current episode per topic | Deleted when the episode ends |
| `alerts(id PK, topic_id, kind, sent_at, heat, subject)` | kind = `hot` or `capped`; cooldown, daily cap, digest | 30 days |
| `phrase_counts(hour, phrase, items, PK(hour, phrase))` | Phrase frequency per IST hour of publication; singletons pruned after 3 h | 8 days |
| `emerging_topics(topic_id PK, phrase, name, bucket, created_at, last_seen_at)` | Auto-created topics | 48 h after last_seen |
| `source_health(source PK, last_ok_at, last_error_at, last_error, consecutive_failures)` | Digest health section | Kept |
| `kv(key PK, value)` | Run index, X-mirror last fetch, last digest | Kept |

Expected database size: under 20 MB.

## 7. Collectors

**Common rules**
- All HTTP goes through the shared client: 10 s timeout (5 s to connect), one retry after 2 s on timeout, connection error or 5xx, browser-like User-Agent, UTF-8 decoding.
- **Circuit breaker:** a collector that failed in 3 or more consecutive runs is retried at most once an hour, so an unreachable source cannot slow every run.
- A collector exception is caught by the registry, logged (collector id and error class only), recorded in `source_health`, and the run continues.
- Items published more than 24 h ago are ignored, except YouTube videos, which are tracked for 72 hours (and kept 30 days for baselines).
- Collectors run concurrently in a thread pool (max 8 workers). Target run time is under 2 minutes.

| Collector | Endpoint | Cadence | Emits |
|---|---|---|---|
| google_trends | `https://trends.google.com/trending/rss?geo=IN` | Every run | `search_trend` per trending item. Text = news item titles. `approx_traffic` parsed from "20K+" to 20000 |
| google_news | `https://news.google.com/rss/search?q=<query>+when:1h&hl=en-IN&gl=IN&ceid=IN:en`; Hindi queries use `hl=hi&gl=IN&ceid=IN:hi` | Every run, 11 queries | `news`. Outlet parsed from the "Headline - Source" title |
| news_feeds | 12 finance-section RSS feeds (below) | Every run | `news` |
| regulators | `https://rbi.org.in/pressreleases_rss.xml`, `https://www.sebi.gov.in/sebirss.xml` | Every run | `regulator` for items not seen before |
| x_trends | `https://trends24.in/india/`; fallback `https://getdaytrends.com/india/` | When 55+ min since last success | `x_trend` for the current top 50 with rank |
| youtube | Channel RSS `https://www.youtube.com/feeds/videos.xml?channel_id=<id>` (no API key) | Every run, one third of channels | `video` for videos up to 72 h old, with views and outlier score |
| reddit | `https://www.reddit.com/r/<sub>/rising/.rss` | Every run, best-effort | `forum` with `rising_rank` |
| markets | `https://query1.finance.yahoo.com/v8/finance/chart/<symbol>?interval=5m&range=1d` | Every run | `market` when a move crosses its threshold |

### google_news queries (sources.yaml, initial)

1. `"mutual fund" OR SIP OR NFO OR "index fund" OR ELSS`
2. `"income tax" OR ITR OR "tax regime" OR "capital gains" OR TDS OR GST`
3. `"home loan" OR EMI OR "credit card" OR CIBIL OR "fixed deposit" OR insurance`
4. `EPFO OR NPS OR PPF OR pension OR retirement OR UPI`
5. `Sensex OR Nifty OR "stock market" OR "Dalal Street"`
6. `RBI OR "repo rate" OR inflation OR rupee OR "gold price" OR "crude oil"`
7. `IPO OR GMP OR "F&O" OR SEBI OR multibagger`
8. `PMS OR AIF OR NRI OR "estate planning" OR "family office" OR REIT`
9. `site:moneycontrol.com` (Moneycontrol's own RSS has been frozen since April 2024)
10. Hindi: `शेयर बाजार OR सेंसेक्स OR निफ्टी OR आईपीओ`
11. Hindi: `म्यूचुअल फंड OR आयकर OR आरबीआई OR सोना`

Google News mixes foreign outlets into the India edition (a live test on 2026-09-26 returned Motley Fool, a Thai IPO story and BBC Pidgin). Results are kept only from `.in` domains, domains containing "india" (indiatimes.com, indianexpress.com, ...) and an allowlist of Indian outlets in `sources.yaml`.

### news_feeds (sources.yaml)

| Feed id | URL |
|---|---|
| et_markets | `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms` |
| et_wealth | `https://economictimes.indiatimes.com/wealth/rssfeeds/837555174.cms` |
| et_mf | `https://economictimes.indiatimes.com/mf/rssfeeds/359241701.cms` |
| mint_markets | `https://www.livemint.com/rss/markets` |
| mint_money | `https://www.livemint.com/rss/money` |
| bs_markets | `https://www.business-standard.com/rss/markets-106.rss` |
| bs_finance | `https://www.business-standard.com/rss/finance-103.rss` |
| bs_economy | `https://www.business-standard.com/rss/economy-102.rss` |
| cnbctv18_market | `https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml` |
| cnbctv18_economy | `https://www.cnbctv18.com/commonfeeds/v1/cne/rss/economy.xml` |
| cnbctv18_pf | `https://www.cnbctv18.com/commonfeeds/v1/cne/rss/personal-finance.xml` |
| ndtvprofit | `https://feeds.feedburner.com/ndtvprofit-latest` |

### regulators

Only items published today or yesterday (IST) become signals; SEBI dates carry no time of day. A regulator item affects scoring only if the matcher maps it to a topic; routine unmatched releases (for example, penalties on co-operative banks) are stored but ignored.

### x_trends

Parses the most recent hourly list (top 50, in rank order). If trends24 fails or yields no trends, getdaytrends is tried in the same run.

### youtube

- `channels.yaml` entries: `{id, name}`. Seeded with 91 Indian finance channels (creators, education channels and business news), each verified during planning by resolving its handle and fetching its RSS. Corporate fund-house and insurer channels are excluded because ad-boosted views would look like viral spikes.
- **No API key.** The RSS feed carries each video's view count (`media:statistics views`, measured within about 5% of the live count) and marks Shorts with a `/shorts/` link.
- **Rotation:** channels are split into 3 groups by position in the file; run N fetches group `N % 3`, so each channel's RSS is checked every 45 minutes. RSS lists the latest 15 videos per channel.
- Every fetched video is upserted into `videos` (latest views, `last_seen_at`).
- **Tracking:** videos up to 72 h old, at most the 20 most recent per channel, get an outlier score each time their channel is fetched.
- **Baseline:** for each channel, every stored video last seen at age 6 h or more contributes a projected 72-hour view count, `views / f(age at last sight)`. The baseline is the median of the samples in the same format (Short or long) if there are at least 3, otherwise the median of all samples if there are at least 3, otherwise none (no score). The video being scored is excluded from its own baseline.
- **Outlier score** = `views / (baseline * f(age_h))`, where `f(age_h) = clamp(sqrt(age_h / 72), 0.15, 1.0)`. This is a heuristic and is tunable in settings.
- Each scored video also gets a `hook_type` from `hooks.classify` for the format scoreboard.

### reddit

Initial subreddits: IndiaInvestments, personalfinanceindia, IndianStockMarket, IndianStreetBets, FIREIndia, CreditCardsIndia, IndiaTax, StockMarketIndia. Requests are spaced 3 s apart. A 429 stops Reddit for the rest of the run; a 403 is recorded as a failure. Unauthenticated JSON has been blocked since May 2026 and RSS carries no scores, so position in the rising feed is the only velocity proxy. Failures from GitHub runner IPs are expected at times.

### markets

| Symbol | Meaning | Threshold | Topic |
|---|---|---|---|
| `^NSEI` | Nifty 50 | ±1.5% | market_moves |
| `^BSESN` | Sensex | ±1.5% | market_moves |
| `^NSEBANK` | Bank Nifty | ±2.0% | market_moves |
| `^INDIAVIX` | India VIX | +10% | market_moves |
| `GC=F` | Gold futures | ±2.0% | gold_price |
| `INR=X` | USD/INR | ±0.5% | rupee_forex |
| `^GSPC` | S&P 500 | ±2.0% | us_fed_global |

`pct_move = (regularMarketPrice - chartPreviousClose) / chartPreviousClose * 100`. A signal is emitted only if `regularMarketTime` is within the last 30 minutes (fresh session data), and at most once per symbol, direction and trading date (enforced by the item id). Example title: "Nifty 50 down 2.1% today".

### events (digest only)

`events.yaml` entries: `{date, date_end (optional), name, topic}`. Initial entries:
- RBI MPC decisions: 2026-10-07, 2026-12-04, 2027-02-05.
- US FOMC decisions: 2026-10-28 and 2026-12-09 (US time; the result lands late night or early morning IST).
- Union Budget: 2027-02-01 (expected).
- Advance tax due: 2026-12-15, 2027-03-15.
- Financial year end and tax-saving deadline: 2027-03-31.
- Q2 FY27 results season: 2026-10-10 to 2026-11-14.

Events never change heat.

## 8. Topics and matching

`topics.yaml` schema:

```yaml
- id: gold_price
  name: Gold & silver prices
  bucket: markets          # personal_finance | markets | wealth | trading
  keywords: [gold price, gold rate, silver price, gold etf, sovereign gold bond, सोना, चांदी]
  angles: [data_compare, history_lesson, myth_bust, should_you, explainer]
```

`topics.yaml` also holds `finance_vocab`: words that mark finance context, used in section 9.

### Initial topics (47)

| Bucket | Topics |
|---|---|
| Personal finance (14) | sip_mutual_funds, income_tax, itr_filing, capital_gains_tax, insurance, loans_emi, credit_cards, credit_score, retirement_pension, fixed_income_savings, upi_payments, scams_fraud, salary_budgeting, home_buying |
| Markets & macro (15) | market_moves, rbi_policy, inflation, union_budget, gst, gold_price, rupee_forex, crude_oil, us_fed_global, tariffs_trade, fii_dii_flows, gdp_economy, banking_news, sebi_regulation, ipo_buzz |
| Wealth / HNI (9) | pms_aif, estate_succession, nri_investing, real_estate_vs_equity, global_investing, bonds_debt, unlisted_esop, rich_list_wealth, hni_tax_planning |
| Trading & stocks (9) | fno_trading, stock_moves, smallcap_penny, corporate_actions, earnings_results, trading_psychology, short_seller_fraud, finfluencers, crypto |

### Matching rules

- The matched text is the title plus the first 500 characters of `text`, Unicode NFC-normalized, with whitespace collapsed.
- Latin keywords match case-insensitively on word boundaries (`(?<![a-z0-9])kw(?![a-z0-9])`), so "ipo" does not match "hippo".
- Keywords written in ALL CAPS with 4 or fewer characters (SIP, NPS, UPI, GST, EMI, PPF) match case-sensitively.
- Devanagari keywords match as substrings.
- An item can match several topics.

## 9. New-phrase spike detection

**Input:** titles of items first seen in this run (news, videos, forum posts, regulator items, Google Trends and X trend entries) for counting, and titles of all items published in the last 2 h for detection. Market items are excluded.

1. **Tokenize:** lowercase Latin text and keep Devanagari tokens. Split on punctuation, but keep `&` inside tokens (F&O). Drop pure numbers and 1-character tokens.
2. **Chunk:** split each title at stopwords (English stopwords plus boilerplate: live, updates, today, latest, news, check, know, here, why, what, how, says, said, will, may, top, day, week, amid, after, over, you, your, this, that, big, more, than).
3. **N-grams:** build 2-3 word phrases within each chunk. Also add whole Google Trends titles and X trend names (including hashtags) as phrases. Ignore phrases shorter than 5 characters and phrases containing any settings blocklist entry: daily boilerplate and routine company filings, for example "share price", "stock market today", "top gainers", "trading window", "board meeting".
4. **Count:** for each new item, add 1 to `phrase_counts` for each of its phrases, in the IST hour it was published (first seen, when undated). Singleton rows older than 3 h are pruned.
5. **Burst ratio:** `c2h` = items published in the last 2 h whose title contains the phrase (computed from `items`). The baseline counts come from the 7 days before that window. `baseline = max(7-day hourly average, same-IST-hour average over the previous 7 days, 0.25)`. `ratio = (c2h / 2) / baseline`. The same-hour term suppresses phrases that recur daily, such as market-open headlines.
6. **Emerging if** `ratio >= 4`, `c2h >= 3`, the items span 2 or more distinct feeds, and the phrase has **finance context**. Finance context means at least 50% of its items come from finance-only sources (news_feeds, google_news, youtube, reddit, regulators), or at least 50% contain a `finance_vocab` word.
7. **Subsumption:** if 80% or more of a shorter phrase's items also contain a longer phrase, keep only the longer one. If two phrases share 80% or more of their items, keep the one with more items.
8. **Mapping:** if 60% or more of the phrase's items match a single topic, the phrase is attached to that topic and shown in its brief as a spiking phrase. Otherwise it creates or refreshes the emerging topic `emerging:<slug>`:
   - name: the phrase as capitalised in the first matching headline;
   - bucket: the most common bucket among its items' matched topics (default markets);
   - angles: the default emerging set (hot_take_news, explainer, timeline, myth_bust, faq).
9. Emerging topics are scored like static topics. Their items are those whose normalized title contains the phrase. They use a news prior of μ0 = 0.5, σ0 = 1.0 and expire 48 h after last activity.

## 10. Scoring, stages and alert rule

Computed every run for every static and emerging topic.

### Values (z-scored sources)

| Source | Value |
|---|---|
| news | Distinct news items matched to the topic, published (or first seen, when no date) in the last 60 min |
| youtube | Sum of `min(outlier, 10)` over matched videos up to 48 h old with outlier ≥ 1.5 |
| forum | Matched posts currently in the Reddit rising feeds |

Only non-zero values are stored. Baselines treat runs without a row as zero.

### Baseline and z-score

Samples are the topic's values over the previous 7 days from runs whose IST hour is h-1, h or h+1 (the current hour h). This covers about 84 runs and handles daily seasonality. With n samples, mean m and variance v:

- `mu = (n*m + P*mu0) / (n + P)`
- `sigma^2 = (n*v + P*sigma0^2) / (n + P)`
- `sigma_eff = max(sigma, floor)`
- `z = (value - mu) / sigma_eff` if `value >= min_value`, else 0

where `P = 4`, so real history outweighs the priors within a day; with no history at all the priors act as fixed thresholds.

**Warm-up:** HOT alerts are held back for the first 24 hours after the very first run. A live test showed why: on day one, busy topics (Nifty moves, IPOs, retirement) look unusual against the priors and would all alert. Topics are still scored during warm-up and appear in the digest.

| Source | mu0 | sigma0 | floor | min_value | weight |
|---|---|---|---|---|---|
| news | 1.0 | 1.5 | 1.0 | 3 | 1.0 |
| youtube | 0.3 | 1.0 | 1.0 | 1.5 | 0.8 |
| forum | 0.2 | 0.8 | 0.8 | 2 | 0.5 |

### Bonuses (sources that are spikes by definition)

For each bonus type, take the max over the topic's signals.

| Type | Condition | Points |
|---|---|---|
| search_trend | Topic matched in Google Trending India right now | approx_traffic ≥ 500K: 5; ≥ 100K: 4; ≥ 20K: 3; else 2 |
| x_trend | Matched in the latest X India top 50 (fetch no older than 75 min) | rank 1-10: 4; 11-25: 3; 26-50: 2 |
| market | Threshold crossed, event no older than 6 h | 3; move ≥ 2× threshold: 4 |
| regulator | New matched RBI/SEBI item no older than 6 h | 2 |

### Heat and source count

- `H = 1.0*clip(z_news, 0, 6) + 0.8*clip(z_youtube, 0, 6) + 0.5*clip(z_forum, 0, 6) + sum(bonuses)`
- `n_sources` = number of source types with z ≥ 2 or bonus > 0.

### Stages

Thresholds: watch `W = 4.0`, hot `T = 6.0`.

- **Episode:** starts at the first run with H ≥ W; ends after 4 consecutive runs with H < W.

Stages are evaluated in this order; the first that applies wins:

1. **Quiet:** not in an episode.
2. **Fading:** H < W while the episode is still open, or H < previous H < the one before (two consecutive declines).
3. **Emerging:** H ≥ previous H and episode age ≤ 2 h.
4. **Peaking:** anything else in an episode.

### HOT alert rule (all must hold)

1. H ≥ T and H ≥ previous H.
2. n_sources ≥ 2, or a single bonus ≥ 3.
3. Stage is Emerging or Peaking.
4. No HOT alert for this topic in the last 12 h, or H ≥ 2 × the heat at the last alert.
5. Fewer than 4 HOT alerts sent today (IST date). Otherwise record `kind = capped` for the digest instead of sending.

When several topics qualify in one run they are processed in descending heat order. Urgency text: Emerging means "post within 3h"; Peaking means "post within 1h".

**Worked examples (used as tests)**
- **Gold record:** news 14 items/hr against mu 2, sigma 1.5 gives z 8, clipped to 6; Google Trending 50K+ adds 3; gold futures +2.3% adds 3. H = 12, n_sources = 3: HOT.
- **Slow drift:** news 4 items/hr against mu 2, sigma 1.5 gives z 1.33. H = 1.33: Quiet, no alert.

All thresholds, weights, priors, caps and cooldowns live in `settings.yaml`.

## 11. Briefs and angles

### Brief contents (in order)

1. Topic name, bucket, stage and urgency.
2. **Headline:** the most recent matched news title, or the trending title.
3. **Why now:** up to 6 evidence lines, each with a number and a link. For example:
   - "Google Trends India: 'gold rate' 50K+ searches, trending since 09:40 IST"
   - "News: 14 articles in the last hour (normally about 2)"
   - "X India trending: #GoldPrice, rank 9"
   - "YouTube: '<title>' by <creator>, 4.1x their normal views (Short)"
   - "Reddit: 3 posts rising in r/IndiaInvestments"
   - "Market: gold futures +2.3% today"
   - "Regulator: SEBI, <title>"
4. **Spiking phrases** attached to the topic, if any.
5. **Angles:** the top 3 angle types, each with its LinkedIn, X and Instagram format and one filled hook.
6. **Hooks working right now:** up to 3 matched YouTube videos from the last 72 h with outlier ≥ 2.0: title, creator, Short or long, score, link.

### Angle playbook (angles.yaml)

```yaml
- id: myth_bust
  name: Myth vs fact
  formats:
    linkedin: "Text post: 3 myths, one line each, plus the fact (150-250 words)"
    x: "Thread: one myth per post, 5-6 posts"
    instagram: "Reel 30-45 s 'Myth or fact?' or 7-slide carousel"
  hooks:
    - "Everyone's talking about {topic}. Here's what most people get wrong."
    - "3 myths about {topic} I hear every week."
```

There are 15 angle types: hot_take_news, explainer, before_after_rule, myth_bust, data_compare, history_lesson, mistakes_list, checklist, faq, red_flags, should_you, what_if_calculator, contrarian_take, timeline, poll.

Hook placeholders are `{topic}` (topic name or phrase) and `{headline}`.

### Angle selection

- **Candidates:** the topic's `angles` list; emerging topics use the default emerging set (section 9).
- **Score:** scoreboard multiplier × stage weight.
  - Scoreboard multiplier: the angle type's median YouTube outlier score over 7 days, across shorts and long videos combined, or 1.0 if it has fewer than 3 videos.
  - Stage weight: Emerging gives ×1.3 to hot_take_news, explainer and before_after_rule. Peaking gives ×1.3 to myth_bust, data_compare, contrarian_take and mistakes_list. Everything else is ×1.0.
- **Pick:** the top 3. Ties go to the earlier entry in the topic's list.

### Format scoreboard (hooks.py)

Each tracked video title is classified by ordered, case-insensitive regex rules (English plus common Hinglish); the first match wins, and a title matching nothing is `other`. Initial rule order:

1. red_flags (red flag, beware, warning, fraud, scam, dhokha, savdhan)
2. mistakes_list (mistake, galti, avoid, never do, don't, mat karo)
3. myth_bust (myth, truth, sach, reality, lie)
4. data_compare (vs, versus, compare, comparison, better than)
5. before_after_rule (new rule, naya niyam, rule change, old vs new)
6. hot_take_news (breaking, just in, big news, announced, badi khabar)
7. history_lesson (history, last time, since 19xx/20xx, years of data, N saal)
8. what_if_calculator (a ₹/rs/lakh/crore amount together with month/year/salary/sip/emi; calculate; kitna)
9. should_you (should you, should i, kya ... chahiye, worth it, right time)
10. contrarian_take (unpopular, nobody tells, no one tells, overrated, wrong)
11. checklist (checklist, steps, things to, tips, before you)
12. faq (questions, faq, asked, answered, sawal)
13. explainer (explained, what is, kya hai, how ... works, kaise, basics, guide)
14. timeline (what happened, timeline, story of, full story)

The rules are refined against fixtures during implementation. For each angle type × format with 3 or more videos in the last 7 days, the scoreboard records the median outlier score and an example title.

## 12. Email

- **Transport:** SMTP `smtp.gmail.com:587` with STARTTLS, logging in with `SMTP_USER` / `SMTP_APP_PASSWORD`. Use a dedicated Google account with 2-Step Verification and an app password. Recipients come from `ALERT_TO` (comma-separated). Gmail's free limit is 500 recipients per day.
- **Style:** neutral styling (black and grey text, simple tables), no colors that carry meaning, no emoji. HTML plus a plain-text alternative.
- **HOT email:** subject `HOT [<bucket name>] <topic name>: <headline truncated to 60 chars> — post within <N>h`. Bucket names are Personal finance, Markets & macro, Wealth/HNI, Trading & stocks. The body is the brief (section 11).
- **Digest:** subject `Radar digest <DD Mon> — <N> trends`. Sections:
  1. **Top trends, last 24 h (up to 10):** topic, peak heat, current stage, alert status (sent / capped / none), one evidence line, link.
  2. **Near misses (up to 5):** topics whose peak heat reached W or more without a HOT alert.
  3. **Format scoreboard:** the top 5 angle type × format rows by median outlier score over 7 days, each with an example title.
  4. **Coming up (next 7 days):** events with 2 prep angle ideas from the event topic's angles.
  5. **Source health:** sources failing for 6 h or more, or "All sources OK".
- **Dry run:** `--dry-run` writes `out/<UTC timestamp>-<kind>-<topic>.html` and prints the subjects. No SMTP.
- **Send failure:** a HOT email is retried once. If it still fails, the alert is not recorded, so the next run retries it, and the current run exits non-zero after finishing its other work.

## 13. Operations

### Workflows

- **radar.yml**
  - Triggers: `schedule: cron "4,19,34,49 * * * *"` (off-peak minutes reduce GitHub delay) and `workflow_dispatch`.
  - `concurrency: {group: radar-state, cancel-in-progress: false}`. ubuntu-latest, `timeout-minutes: 10`.
  - Steps: checkout → setup-python 3.12 with pip cache → `pip install -r requirements.txt` → `actions/cache/restore` (path `radar.db`, key `radar-db-${{ github.run_id }}-${{ github.run_attempt }}`, restore-keys `radar-db-`) → `python -m radar run` → `actions/cache/save` (`if: always()`, same key).
- **digest.yml**
  - Triggers: `schedule: cron "30 2 * * *"` and `workflow_dispatch`.
  - Same concurrency group and cache restore/save; runs `python -m radar digest`.
  - `permissions: actions: write`. On day 1 of each month it runs `gh workflow enable radar.yml` and `gh workflow enable digest.yml`, so GitHub's 60-day inactivity auto-disable for scheduled workflows in public repos never triggers.
- **ci.yml:** on push and pull_request, run `pytest`.
- **Before email is configured:** if `SMTP_USER` is empty, radar.yml and digest.yml run with `--dry-run` and post a warning annotation. The radar keeps building history and nothing fails; adding the secrets switches to real email.

### Secrets and logging

- Repository secrets: `SMTP_USER`, `SMTP_APP_PASSWORD`, `ALERT_TO`. They are passed only to the steps that need them. No other credentials are needed.
- Workflow logs are public. Log counts, topic ids and source health only. Never print secrets, recipients or email bodies.

### State

`radar.db` lives in the Actions cache and is pruned every run (retention per section 6). If the cache is lost, the radar starts a fresh database and the priors (section 10) keep alerting sane while baselines rebuild over about 2 days.

### Error handling summary

| Failure | Behaviour |
|---|---|
| One collector errors or times out | Logged, `source_health` updated, run continues |
| A collector fails 3 runs in a row | Retried at most once an hour (circuit breaker) |
| Reddit 429 or connection failure | Reddit skipped for the rest of the run |
| One YouTube channel's RSS fails | That channel is skipped until its next rotation; the rest continue |
| Malformed item | Item skipped and counted in logs |
| All collectors fail in one run | Run exits non-zero; GitHub emails the repo owner |
| HOT email send fails twice | Alert not recorded (retried next run); run exits non-zero |
| Source failing for 6 h or more | Listed in the digest's Source health section |
| Database missing or corrupt | Fresh schema created; priors cover warm-up |

## 14. Testing

- **Framework:** pytest. Tests never touch the network.
- **Parser tests:** each collector's `parse` is tested against small fixtures copied from the real formats sampled on 2026-09-26: `google_trends_in.xml`, `google_news.xml`, `news_feed.xml`, `sebi.xml`, `trends24_india.html`, `getdaytrends_india.html`, `youtube_channel.xml`, `reddit_rising.xml`, `yahoo_chart.json`. Live endpoints are exercised by the acceptance run, not by unit tests.
- **Unit tests:**
  - matcher: word boundaries, the ALL-CAPS rule, Devanagari, multiple topics.
  - phrases: tokenize, chunk, burst ratio, same-hour baseline, finance context, subsumption, mapping to topic vs emerging.
  - scorer: priors and hour window, implicit zeros, bonuses, heat, stages, alert rule.
  - hooks: classifier ordering.
  - briefs: angle selection (candidates, scoreboard multiplier, stage weight, tie-break), hooks filled.
  - emailer: subject formats, all sections present, no emoji in rendered output.
  - store: schema creation, pruning.
- **Scenario tests (synthetic run sequences through scorer):**
  1. A sharp spike produces exactly one HOT alert.
  2. A slow drift produces none.
  3. A fading topic produces none.
  4. The same topic 3 h after an alert is suppressed by the cooldown, unless its heat has doubled.
  5. Five qualifying topics in one IST day produce 4 HOT alerts and 1 capped.
  6. The two worked examples in section 10.
- **Acceptance:** `python -m radar run --dry-run` on the local machine produces briefs from live sources; the first scheduled GitHub run succeeds; the first digest arrives.

## 15. Phase 2 (out of scope here)

- Instagram Business Discovery collector for creator Reel views (needs a Meta app and an Instagram professional account).
- LLM-written angles and post drafts.
- X API pay-per-use trends (about $0.01 per request, roughly $7/month hourly).
- SerpApi Google Trends with the Business & Finance category.
- Feedback buttons in emails to tune thresholds.

## 16. References (research of 2026-09-26)

- Google Trends RSS: https://trends.google.com/trending/rss?geo=IN
- YouTube channel RSS (example): https://www.youtube.com/feeds/videos.xml?channel_id=UCe3qdG0A_gr-sEdat5y2twQ
- X API pricing (pay-per-use): https://docs.x.com/x-api/getting-started/pricing
- Reddit unauthenticated JSON blocked, RSS working: https://dev.to/listwright/reddits-json-returns-403-in-2026-the-rss-feeds-still-answer-1gg5
- LinkedIn scraping litigation (Proxycurl): https://www.socialmediatoday.com/news/linkedin-wins-legal-case-data-scrapers-proxycurl/756101/
- RBI MPC schedule FY2026-27: https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=62422
- FOMC calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
