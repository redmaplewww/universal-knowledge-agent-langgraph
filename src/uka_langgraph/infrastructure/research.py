from __future__ import annotations

import hashlib
import html
import json
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

from uka_langgraph.domain.models import WebSearchBatch, WebSearchObservation


class DisabledWebSearchProvider:
    revision = "web-search:disabled"

    def search(self, query: str, *, count: int = 5) -> WebSearchBatch:
        return WebSearchBatch(
            query=query,
            status="disabled",
            provider_revision=self.revision,
            error_type="web_research_disabled",
        )


class ZhipuWebSearchProvider:
    """Bounded structured search; returned pages are observations, not trusted truth."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        engine: str = "search_std",
        timeout_seconds: float = 20.0,
    ) -> None:
        if not endpoint.casefold().startswith("https://"):
            raise ValueError("web search endpoint must use HTTPS")
        self.api_key = api_key
        self.endpoint = endpoint
        self.engine = engine
        self.timeout_seconds = timeout_seconds
        self.revision = f"zhipu-web-search:{engine}"

    def search(self, query: str, *, count: int = 5) -> WebSearchBatch:
        normalized_query = " ".join(query.split())[:70]
        if not normalized_query:
            return WebSearchBatch(
                query=query,
                status="invalid_query",
                provider_revision=self.revision,
                error_type="empty_query",
            )
        body = json.dumps(
            {
                "search_query": normalized_query,
                "search_engine": self.engine,
                "search_intent": False,
                "count": max(1, min(count, 10)),
                "search_recency_filter": "noLimit",
                "content_size": "medium",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "universal-knowledge-agent/0.3",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
        except (
            TimeoutError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            return WebSearchBatch(
                query=normalized_query,
                status="unavailable",
                provider_revision=self.revision,
                error_type=type(exc).__name__,
            )
        raw_results = payload.get("search_result", []) if isinstance(payload, dict) else []
        observations: list[WebSearchObservation] = []
        if isinstance(raw_results, list):
            for rank, item in enumerate(raw_results[: max(1, min(count, 10))], start=1):
                if not isinstance(item, dict):
                    continue
                url = str(item.get("link") or "").strip()
                snippet = " ".join(str(item.get("content") or "").split())[:4_000]
                title = " ".join(str(item.get("title") or "").split())[:500]
                if not url or not snippet:
                    continue
                observations.append(
                    WebSearchObservation(
                        observation_id=stable_id(
                            "webobs", normalized_query, url, snippet
                        ),
                        query=normalized_query,
                        title=title,
                        url=url[:2_000],
                        snippet=snippet,
                        media=str(item.get("media") or "")[:200],
                        published_at=_optional_text(item.get("publish_date")),
                        rank=rank,
                    )
                )
        return WebSearchBatch(
            query=normalized_query,
            status="completed" if observations else "no_results",
            observations=tuple(observations),
            provider_revision=self.revision,
        )


class DuckDuckGoHTMLSearchProvider:
    """Credential-free fallback for local evaluation; does not fetch result pages."""

    revision = "duckduckgo-html:v1"
    endpoint = "https://html.duckduckgo.com/html/"

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, count: int = 5) -> WebSearchBatch:
        normalized_query = " ".join(query.split())[:200]
        if not normalized_query:
            return WebSearchBatch(
                query=query,
                status="invalid_query",
                provider_revision=self.revision,
                error_type="empty_query",
            )
        url = f"{self.endpoint}?{urllib.parse.urlencode({'q': normalized_query})}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/123 Safari/537.36"
                )
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(2_000_000).decode("utf-8", errors="replace")
        except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            return WebSearchBatch(
                query=normalized_query,
                status="unavailable",
                provider_revision=self.revision,
                error_type=type(exc).__name__,
            )
        parser = _DuckDuckGoResultParser()
        parser.feed(body)
        observations = tuple(
            WebSearchObservation(
                observation_id=stable_id(
                    "webobs", normalized_query, item["url"], item["snippet"]
                ),
                query=normalized_query,
                title=item["title"][:500],
                url=item["url"][:2_000],
                snippet=item["snippet"][:4_000],
                media=urllib.parse.urlsplit(item["url"]).netloc[:200],
                rank=rank,
            )
            for rank, item in enumerate(parser.results[: max(1, min(count, 10))], start=1)
        )
        return WebSearchBatch(
            query=normalized_query,
            status="completed" if observations else "no_results",
            observations=observations,
            provider_revision=self.revision,
        )


class FallbackWebSearchProvider:
    def __init__(self, primary, fallback) -> None:
        self.primary = primary
        self.fallback = fallback
        self.revision = f"fallback:{primary.revision}->{fallback.revision}"

    def search(self, query: str, *, count: int = 5) -> WebSearchBatch:
        primary = self.primary.search(query, count=count)
        if primary.status == "completed" and primary.observations:
            return primary
        fallback = self.fallback.search(query, count=count)
        if fallback.status == "completed" and fallback.observations:
            return fallback
        if fallback.status == "no_results":
            return fallback
        if primary.status == "no_results":
            return primary
        return WebSearchBatch(
            query=query,
            status="unavailable",
            provider_revision=self.revision,
            error_type=fallback.error_type or primary.error_type or "no_results",
        )


class _DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture = ""
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div" and "web-result" in classes:
            self._current = {"title": "", "url": "", "snippet": ""}
            self._depth = 1
            return
        if self._current is not None and tag == "div":
            self._depth += 1
        if self._current is None or tag != "a":
            return
        if "result__a" in classes:
            self._capture = "title"
            self._current["url"] = _duckduckgo_target(attributes.get("href") or "")
        elif "result__snippet" in classes:
            self._capture = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag == "a":
            self._capture = ""
        if tag == "div":
            self._depth -= 1
            if self._depth == 0:
                if all(self._current.get(key) for key in ("title", "url", "snippet")):
                    self.results.append(self._current)
                self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._capture:
            value = " ".join(html.unescape(data).split())
            if value:
                self._current[self._capture] = (
                    f"{self._current[self._capture]} {value}"
                ).strip()


def _duckduckgo_target(value: str) -> str:
    href = html.unescape(value)
    if href.startswith("//"):
        href = f"https:{href}"
    parsed = urllib.parse.urlsplit(href)
    target = urllib.parse.parse_qs(parsed.query).get("uddg", [href])[0]
    target_parsed = urllib.parse.urlsplit(target)
    return target if target_parsed.scheme in {"http", "https"} else ""


def _optional_text(value: Any) -> str | None:
    rendered = str(value).strip() if value is not None else ""
    return rendered or None


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"
