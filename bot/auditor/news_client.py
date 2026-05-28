"""Free crypto news fetcher — RSS-first, no API key required.

Default provider chain is ``rss`` which aggregates major crypto outlets
(CoinDesk, Cointelegraph, Decrypt, The Block, Bitcoin Magazine). RSS feeds
have no rate limits and require no keys, making them the most reliable free
option for a paper-trading auditor.

Opt-in JSON providers (set ``providers`` to include them):
- ``coingecko`` — CoinGecko ``/news`` endpoint (free tier; subject to throttling).
- ``cryptopanic`` — CryptoPanic public posts endpoint. *Deprecated*: rate-limited
  and increasingly paid; kept for users with an existing key.

Stdlib only (urllib + xml.etree.ElementTree). Never raises from the public
``fetch_headlines`` method — failures degrade to cached results then [].
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, Sequence

logger = logging.getLogger(__name__)

USER_AGENT = "EthTradingBot Auditor/1.0 (+paper-trading)"
DEFAULT_TIMEOUT_SEC = 10.0
CACHE_TTL_SEC = 10 * 60  # 10 minutes

_VALID_SENTIMENTS = {"positive", "negative", "neutral"}

# Major crypto outlets that publish a public RSS feed and don't require a key.
# Each entry is (display name, feed URL). Override via the AUDITOR_RSS_FEEDS env
# var (comma-separated "Name|URL,Name|URL,...") or by passing ``rss_feeds`` to
# the NewsClient constructor.
DEFAULT_RSS_FEEDS: tuple[tuple[str, str], ...] = (
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
)

# Common tickers we recognise in headline text. Kept short on purpose to avoid
# false matches (e.g. "OP" in "operation"). Expand cautiously.
_TICKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (
        symbol,
        re.compile(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])", re.IGNORECASE),
    )
    for symbol in (
        "BTC", "ETH", "SOL", "ADA", "XRP", "DOT", "LINK", "AVAX",
        "ATOM", "LTC", "DOGE", "BNB", "UNI", "AAVE", "ARB", "OP", "POL",
        "MATIC",
    )
)


@dataclass(frozen=True)
class NewsHeadline:
    title: str
    url: str
    published_at: str
    source: str
    tickers: list[str]
    sentiment: str  # "positive" | "negative" | "neutral" | "unknown"


def _normalize_sentiment(value: str | None) -> str:
    if not value:
        return "unknown"
    text = value.lower().strip()
    return text if text in _VALID_SENTIMENTS else "unknown"


def _extract_tickers(*texts: str) -> list[str]:
    """Return crypto tickers found in any of the supplied text fragments."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return []
    found: list[str] = []
    for symbol, pattern in _TICKER_PATTERNS:
        if pattern.search(blob) and symbol not in found:
            found.append(symbol)
    return found


def _normalize_published(value: str | None) -> str:
    """Return a stable ISO-ish published timestamp string."""
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        dt = parsedate_to_datetime(text)
        if dt is not None:
            return dt.isoformat()
    except (TypeError, ValueError):
        pass
    return text


def _parse_provider_list(raw: str | Iterable[str]) -> list[str]:
    if isinstance(raw, str):
        items = [p.strip().lower() for p in raw.split(",")]
    else:
        items = [str(p).strip().lower() for p in raw]
    cleaned = [p for p in items if p]
    return cleaned or ["rss"]


def parse_rss_feed_env(raw: str) -> tuple[tuple[str, str], ...]:
    """Parse ``Name|URL,Name|URL`` env strings into the RSS feed tuple.

    Empty/invalid entries are skipped silently so a typo in ``.env`` never
    crashes the auditor.
    """
    if not raw:
        return DEFAULT_RSS_FEEDS
    out: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "|" in chunk:
            name, url = chunk.split("|", 1)
        else:
            name, url = chunk, chunk
        name = name.strip() or url.strip()
        url = url.strip()
        if url:
            out.append((name, url))
    return tuple(out) if out else DEFAULT_RSS_FEEDS


@dataclass
class _CacheEntry:
    headlines: list[NewsHeadline] = field(default_factory=list)
    at: float = 0.0
    key: str = ""


class NewsClient:
    """Fetch crypto news headlines with retry, fallback, deduplication, and caching."""

    def __init__(
        self,
        *,
        providers: str | Sequence[str] = ("rss",),
        rss_feeds: Sequence[tuple[str, str]] | None = None,
        api_key: str = "",
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        timeout_seconds: float = DEFAULT_TIMEOUT_SEC,
        cache_ttl_seconds: float = CACHE_TTL_SEC,
        urlopen: Callable | None = None,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self.providers = _parse_provider_list(providers)
        self.rss_feeds = tuple(rss_feeds) if rss_feeds else DEFAULT_RSS_FEEDS
        self.api_key = (api_key or "").strip()
        self.max_retries = max(0, max_retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.timeout_seconds = max(1.0, timeout_seconds)
        self.cache_ttl_seconds = max(0.0, cache_ttl_seconds)
        self._urlopen = urlopen or urllib.request.urlopen
        self._time = time_func
        self._cache = _CacheEntry()

    @property
    def provider(self) -> str:
        """Comma-joined provider string for status display."""
        return ",".join(self.providers)

    def fetch_headlines(
        self,
        assets: Sequence[str],
        max_items: int,
    ) -> list[NewsHeadline]:
        """Return up to ``max_items`` headlines tagged with ``assets``.

        Never raises. On total failure returns the cache (or [] when empty).
        """
        max_items = max(1, int(max_items or 0))
        cache_key = self._key(assets, max_items)
        now = self._time()
        if (
            self._cache.headlines
            and cache_key == self._cache.key
            and (now - self._cache.at) < self.cache_ttl_seconds
        ):
            return list(self._cache.headlines)

        aggregated: list[NewsHeadline] = []
        for provider in self.providers:
            try:
                fetched = self._fetch_provider(provider, assets, max_items)
            except Exception as exc:  # noqa: BLE001 — never crash the bot
                logger.warning("News provider %s failed entirely: %s", provider, exc)
                fetched = []
            if fetched:
                aggregated.extend(fetched)
            if len(_dedupe(aggregated)) >= max_items:
                break

        deduped = _dedupe(aggregated)
        if assets:
            asset_set = {a.upper() for a in assets if a}
            preferred = [h for h in deduped if not h.tickers or set(h.tickers) & asset_set]
            if preferred:
                deduped = preferred + [h for h in deduped if h not in preferred]
        result = deduped[:max_items]

        if result:
            self._cache = _CacheEntry(headlines=list(result), at=now, key=cache_key)
            return result

        return list(self._cache.headlines)

    def _fetch_provider(
        self,
        provider: str,
        assets: Sequence[str],
        max_items: int,
    ) -> list[NewsHeadline]:
        if provider == "rss":
            return self._fetch_rss(max_items)
        if provider == "coingecko":
            return self._fetch_coingecko(max_items)
        if provider == "cryptopanic":
            return self._fetch_cryptopanic(assets, max_items)
        logger.warning("Unknown news provider %r — skipping", provider)
        return []

    def _key(self, assets: Sequence[str], max_items: int) -> str:
        return f"{','.join(sorted(set(assets)))}|{max_items}|{self.provider}"

    def _retrying_get(self, url: str, *, label: str) -> tuple[str, dict | list | None]:
        """Return ``(raw_text, json_parsed_or_none)``.

        Some providers (RSS) need the raw body; JSON providers can use the
        parsed value directly. ``json_parsed_or_none`` is best-effort: it's
        ``None`` when the body isn't valid JSON, even though ``raw_text`` is
        still returned for the RSS path to consume.
        """
        attempts = self.max_retries + 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with self._urlopen(request, timeout=self.timeout_seconds) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                if not raw:
                    return ("", None)
                try:
                    return (raw, json.loads(raw))
                except json.JSONDecodeError:
                    return (raw, None)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                wait = self.backoff_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "News %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    label, attempt, attempts, type(exc).__name__, wait,
                )
                if wait > 0:
                    time.sleep(wait)
        if last_exc is not None:
            logger.warning("News %s gave up: %s", label, last_exc)
        return ("", None)

    def _fetch_rss(self, max_items: int) -> list[NewsHeadline]:
        out: list[NewsHeadline] = []
        per_feed_cap = max(1, max_items)
        for name, url in self.rss_feeds:
            raw, _ = self._retrying_get(url, label=f"rss:{name}")
            if not raw:
                continue
            try:
                root = ET.fromstring(raw)
            except ET.ParseError as exc:
                logger.warning("RSS %s parse error: %s", name, exc)
                continue
            items = _iter_rss_items(root)
            count = 0
            for item in items:
                if count >= per_feed_cap:
                    break
                title = (_text_of(item, "title") or "").strip()
                if not title:
                    continue
                link = (_text_of(item, "link") or "").strip()
                if not link:
                    # Atom feeds use <link href="..."/>
                    link_el = item.find("link") or item.find("{http://www.w3.org/2005/Atom}link")
                    if link_el is not None:
                        link = (link_el.get("href") or "").strip()
                description = _text_of(item, "description") or ""
                published_raw = (
                    _text_of(item, "pubDate")
                    or _text_of(item, "published")
                    or _text_of(item, "{http://www.w3.org/2005/Atom}updated")
                    or _text_of(item, "{http://purl.org/dc/elements/1.1/}date")
                    or ""
                )
                published = _normalize_published(published_raw)
                categories = [
                    (el.text or "").strip()
                    for el in item.findall("category")
                    if el is not None and (el.text or "").strip()
                ]
                tickers = _extract_tickers(title, description, " ".join(categories))
                out.append(
                    NewsHeadline(
                        title=title,
                        url=link,
                        published_at=published,
                        source=name,
                        tickers=tickers,
                        sentiment="unknown",
                    )
                )
                count += 1
        return out

    def _fetch_coingecko(self, max_items: int) -> list[NewsHeadline]:
        url = "https://api.coingecko.com/api/v3/news"
        _, data = self._retrying_get(url, label="coingecko")
        if not isinstance(data, dict):
            return []
        items = data.get("data") or []
        out: list[NewsHeadline] = []
        for item in items[: max(1, int(max_items))]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            tickers_raw = item.get("categories") or item.get("symbols") or []
            tickers = [str(t).upper() for t in tickers_raw if t]
            if not tickers:
                tickers = _extract_tickers(title)
            out.append(
                NewsHeadline(
                    title=title,
                    url=str(item.get("url") or ""),
                    published_at=_normalize_published(
                        item.get("updated_at") or item.get("published_at") or ""
                    ),
                    source=str(item.get("author") or item.get("news_site") or "coingecko"),
                    tickers=tickers,
                    sentiment=_normalize_sentiment(item.get("sentiment")),
                )
            )
        return out

    def _fetch_cryptopanic(self, assets: Sequence[str], max_items: int) -> list[NewsHeadline]:
        params: dict[str, str] = {"public": "true"}
        symbols = ",".join(sorted({a.upper() for a in assets if a}))
        if symbols:
            params["currencies"] = symbols
        if self.api_key:
            params["auth_token"] = self.api_key
        url = "https://cryptopanic.com/api/v1/posts/?" + urllib.parse.urlencode(params)
        _, data = self._retrying_get(url, label="cryptopanic")
        if not isinstance(data, dict):
            return []
        items = data.get("results") or []
        out: list[NewsHeadline] = []
        for item in items[: max(1, int(max_items))]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            currencies = item.get("currencies") or []
            tickers = [
                str(c.get("code") or "").upper()
                for c in currencies
                if isinstance(c, dict) and c.get("code")
            ]
            source = ""
            src_obj = item.get("source")
            if isinstance(src_obj, dict):
                source = str(src_obj.get("title") or src_obj.get("domain") or "")
            sentiment = _classify_cryptopanic_votes(item.get("votes"))
            out.append(
                NewsHeadline(
                    title=title,
                    url=str(item.get("url") or item.get("source_url") or ""),
                    published_at=_normalize_published(item.get("published_at") or ""),
                    source=source,
                    tickers=tickers,
                    sentiment=sentiment,
                )
            )
        return out


def _classify_cryptopanic_votes(votes: dict | None) -> str:
    if not isinstance(votes, dict):
        return "unknown"
    positive = int(votes.get("positive", 0) or 0)
    negative = int(votes.get("negative", 0) or 0)
    if positive == 0 and negative == 0:
        return "neutral"
    if positive > negative * 1.5:
        return "positive"
    if negative > positive * 1.5:
        return "negative"
    return "neutral"


def _iter_rss_items(root: ET.Element) -> list[ET.Element]:
    """Return ``<item>`` elements from RSS 2.0 or ``<entry>`` from Atom."""
    items = root.findall(".//item")
    if items:
        return items
    return root.findall(".//{http://www.w3.org/2005/Atom}entry")


def _text_of(element: ET.Element, tag: str) -> str:
    el = element.find(tag)
    if el is None:
        return ""
    return (el.text or "").strip()


def _dedupe(headlines: Iterable[NewsHeadline]) -> list[NewsHeadline]:
    """Drop duplicates keyed on URL (or title when URL missing)."""
    seen: set[str] = set()
    out: list[NewsHeadline] = []
    for h in headlines:
        key = (h.url or h.title).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out
