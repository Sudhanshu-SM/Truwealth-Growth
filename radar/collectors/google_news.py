"""Google News RSS searches, in English and Hindi, Indian outlets only. Each search looks back over its own `window`
(the block's default is the last hour) and tags its items with the genres of the search."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from radar.collectors import Context, gather
from radar.models import Signal
from radar.rss import parse_feed
from radar.text import slugify

# A US SEC filing ("Form 4 Acme Ltd ...", "Form 8-K ..."): in.investing.com sends them and they match genre searches by
# company name. Named forms, not "Form <any number>": Indian tax stories start "Form 16" (itr_filing's own keyword),
# "Form 60" or "Form 10-IEA".
SEC_FILING = re.compile(r"Form (?:[345]|144|13[DFG]|\d+-[KQF])\b")


def indian_source(url: str, allowed_domains: frozenset[str]) -> bool:
    """True for .in domains, domains containing 'india', and the allowlist in sources.yaml."""
    host = (urlparse(url).hostname or "").removeprefix("www.")
    return host.endswith(".in") or "india" in host or any(host == d or host.endswith("." + d) for d in allowed_domains)


def parse(raw: bytes, lang: str = "en", allowed_domains: frozenset[str] = frozenset(),
          genres: tuple[str, ...] = ()) -> list[Signal]:
    out = []
    for e in parse_feed(raw):
        if (not e.title or SEC_FILING.match(e.title)
                or (e.source_url and not indian_source(e.source_url, allowed_domains))):
            continue
        title = e.title
        suffix = f" - {e.source}" if e.source else ""
        if suffix and title.endswith(suffix):
            title = title[: -len(suffix)].strip()
        out.append(Signal(source="google_news", source_type="news", feed=f"gn:{slugify(e.source or 'unknown')}",
                          title=title, url=e.link, published_at=e.published, lang=lang, genres=genres))
    return out


def collect(ctx: Context) -> list[Signal]:
    cfg = ctx.config.sources["google_news"]
    allowed = frozenset(cfg["allowed_domains"])
    tasks = []
    for q in cfg["queries"]:
        params = dict(cfg["params_hi"] if q["lang"] == "hi" else cfg["params_en"])
        params["q"] = f"{q['q']} {q.get('window', cfg['window'])}"
        tasks.append((q["id"], lambda p=params, lang=q["lang"], genres=tuple(q["genres"]): parse(
            ctx.http.get(cfg["url"], params=p).content, lang, allowed, genres)))
    return gather(tasks)
