from __future__ import annotations

import html
from html.parser import HTMLParser
from datetime import datetime, timezone
import os
import re
import unicodedata
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .providers import ProviderError


def _research_timeout_seconds() -> int:
    try:
        return max(2, min(20, int(os.getenv("RESEARCH_TIMEOUT_SECONDS", "4"))))
    except ValueError:
        return 4


_RESEARCH_STOPWORDS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos", "e", "em", "entre",
    "era", "for", "ha", "na", "nas", "no", "nos", "o", "os", "para", "por", "que", "se", "um", "uma",
    "umas", "uns", "até", "ate", "sobre", "the", "and", "from", "into", "with", "your", "this", "that",
}

# Words that describe the shape of a topic but do not identify its subject.
# They should not be enough to make an unrelated article look relevant.
_GENERIC_TOPIC_TERMS = {
    "atual", "atualidade", "curiosidade", "curiosidades", "data", "desenvolvimento",
    "evolucao", "evoluiu", "fato", "fatos", "futuro", "formacao", "guia", "historia",
    "historico", "impacto", "moderna", "moderno", "origem", "passado", "segredo",
    "trajetoria", "transformacao", "transformacoes", "tendencia", "tendencias",
}


def _topic_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.lower())
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return {token for token in re.findall(r"[a-z0-9]{3,}", plain) if token not in _RESEARCH_STOPWORDS}


def _topic_anchor_tokens(topic: str) -> set[str]:
    """Return subject-bearing terms that distinguish one topic from another."""
    return _topic_tokens(topic) - _GENERIC_TOPIC_TERMS


def _source_relevance(topic: str, title: str, snippet: str) -> tuple[float, list[str]]:
    topic_terms = _topic_tokens(topic)
    anchor_terms = _topic_anchor_tokens(topic)
    source_terms = _topic_tokens(f"{title} {snippet}")
    matched = sorted(topic_terms & source_terms)
    if not topic_terms:
        return 0.25, []
    # A generic overlap such as “história” must not validate an article about
    # the wrong subject. When a topic has anchors, at least one of them must
    # appear in the title/snippet before the result can ground a script.
    if anchor_terms and not (anchor_terms & source_terms):
        return 0.0, []
    coverage = len(matched) / min(len(topic_terms), 6)
    phrase_boost = 0.2 if topic.lower().strip() in f"{title} {snippet}".lower() else 0.0
    return min(1.0, coverage + phrase_boost), matched[:6]


def _source_recency(published_at: str) -> float:
    if not published_at:
        return 0.0
    try:
        published = datetime.strptime(published_at, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        return 0.0
    age_days = max(0.0, (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 86400)
    return max(0.0, 1.0 - min(age_days, 30.0) / 30.0)


def _rank_sources(topic: str, sources: list[dict[str, str]], limit: int = 6) -> list[dict[str, object]]:
    unique: dict[str, dict[str, object]] = {}
    for source in sources:
        key = source.get("url") or source.get("title", "").lower()
        if not key:
            continue
        relevance, matched = _source_relevance(topic, source.get("title", ""), source.get("snippet", ""))
        enriched = dict(source)
        enriched["relevance"] = round(relevance * 100, 1)
        enriched["matched_terms"] = matched
        enriched["recency"] = round(_source_recency(source.get("published_at", "")) * 100, 1)
        current = unique.get(key)
        if current is None or float(enriched["relevance"]) > float(current.get("relevance", 0)):
            unique[key] = enriched
    ranked = sorted(unique.values(), key=lambda item: (float(item.get("relevance", 0)) * 0.8 + float(item.get("recency", 0)) * 0.2), reverse=True)
    relevant = [item for item in ranked if float(item.get("relevance", 0)) > 0]
    return relevant[:limit]


class _DuckParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._kind = ""
        self._href = ""
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "a" and ("result__a" in classes or "result-link" in classes):
            self._kind = "title"
            self._href = attributes.get("href", "")
            self._buffer = []
        elif tag in {"a", "div", "td"} and ("result__snippet" in classes or "result-snippet" in classes):
            self._kind = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._kind:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._kind or (self._kind == "title" and tag != "a"):
            return
        text = " ".join("".join(self._buffer).split())
        if self._kind == "title" and text:
            href = self._href
            if href.startswith("//"):
                href = "https:" + href
            parsed = urlparse(href)
            if parsed.path == "/l/" and parse_qs(parsed.query).get("uddg"):
                href = unquote(parse_qs(parsed.query)["uddg"][0])
            self.results.append({"title": text, "url": href, "snippet": ""})
        elif self._kind == "snippet" and text and self.results:
            self.results[-1]["snippet"] = text
        self._kind = ""
        self._buffer = []


class LiveTrendResearchProvider:
    name = "duckduckgo-live-search"

    @property
    def available(self) -> bool:
        return os.getenv("ENABLE_LIVE_RESEARCH", "1") == "1"

    def create(self, topic: str) -> dict[str, object]:
        if not self.available:
            raise ProviderError("Pesquisa ao vivo desabilitada")
        query = f"{topic} YouTube Shorts TikTok tendências"
        request = Request(
            f"https://lite.duckduckgo.com/lite/?q={quote(query)}",
            headers={"User-Agent": "InHouseVideoStudio/0.3 local research"},
        )
        try:
            with urlopen(request, timeout=_research_timeout_seconds()) as response:
                html = response.read().decode("utf-8", "replace")
        except Exception as exc:
            raise ProviderError(f"busca ao vivo indisponível: {exc}") from exc
        parser = _DuckParser()
        parser.feed(html)
        sources = [item for item in parser.results if item.get("url")][:6]
        if not sources:
            raise ProviderError("a busca ao vivo não retornou fontes")
        score = min(92.0, 48.0 + len(sources) * 5.0)
        return {"status": "live", "query": query, "score": score, "sources": sources, "grounding": "web_search"}


class GoogleNewsResearchProvider:
    """Free public RSS fallback for trend context when the HTML search endpoint is unavailable."""

    name = "google-news-rss"

    @property
    def available(self) -> bool:
        return os.getenv("ENABLE_GOOGLE_NEWS_RSS", "0") == "1"

    def create(self, topic: str) -> dict[str, object]:
        if not self.available:
            raise ProviderError("Google News RSS desabilitado")
        queries = (f"{topic} tendências YouTube Shorts TikTok", f"{topic} tendências", topic)
        sources: list[dict[str, str]] = []
        query = queries[-1]
        last_error: Exception | None = None
        for candidate in queries:
            query = candidate
            request = Request(
                f"https://news.google.com/rss/search?q={quote(candidate)}&hl=pt-BR&gl=BR&ceid=BR:pt-419",
                headers={"User-Agent": "InHouseVideoStudio/0.3 local research"},
            )
            try:
                with urlopen(request, timeout=_research_timeout_seconds()) as response:
                    document = response.read().decode("utf-8", "replace")
                root = ET.fromstring(document)
            except Exception as exc:
                last_error = exc
                continue
            for item in root.findall(".//item")[:8]:
                title = " ".join((item.findtext("title") or "").split())
                url = (item.findtext("link") or "").strip()
                description = html.unescape(item.findtext("description") or "")
                snippet = " ".join(re.sub(r"<[^>]+>", " ", description).split())[:240]
                published = " ".join((item.findtext("pubDate") or "").split())
                if title and url:
                    sources.append({"title": title, "url": url, "snippet": snippet, "published_at": published})
            ranked_preview = _rank_sources(topic, sources, limit=8) if sources else []
            if len(ranked_preview) >= 5 or candidate == queries[-1]:
                break
        if not sources and last_error:
            raise ProviderError(f"Google News RSS indisponível: {last_error}") from last_error
        if not sources:
            raise ProviderError("Google News RSS não retornou fontes")
        sources = _rank_sources(topic, sources)
        if not sources:
            raise ProviderError("Google News RSS não encontrou fontes relacionadas ao tema")
        relevance = sum(float(item.get("relevance", 0)) for item in sources) / max(1, len(sources))
        score = min(92.0, round(42.0 + len(sources) * 4.5 + relevance * 0.35, 1))
        return {
            "status": "live",
            "query": query,
            "score": score,
            "sources": sources,
            "grounding": "news_rss",
            "source_provider": self.name,
            "message": "Sinais públicos recentes filtrados por relevância e recência; a pontuação não é uma métrica oficial de viralidade.",
            "quality": "filtered_live",
        }


class LocalResearchProvider:
    name = "local-topic-brief"

    def create(self, topic: str) -> dict[str, object]:
        return {"status": "fallback", "query": topic, "score": 35.0, "sources": [], "grounding": "local_heuristic", "message": "Sem acesso à busca ao vivo; score reduzido e roteiro tratado como hipótese."}
