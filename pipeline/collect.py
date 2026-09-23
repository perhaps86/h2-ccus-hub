"""RSS 수집.

기사 제목, 링크, 출처, 발행일만 가져온다. 본문은 저장하지 않는다.
피드가 주는 짧은 발췌(snippet)는 분류 입력으로만 쓰고 디스크에 남기지 않는다.
"""

from __future__ import annotations

import html
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml

from schema import RawItem

SOURCES_PATH = Path(__file__).with_name("sources.yaml")
_TAG_RE = re.compile(r"<[^>]+>")
USER_AGENT = "h2-ccus-hub/1.0 (+https://github.com/perhaps86/h2-ccus-hub)"


def strip_html(text: str, limit: int = 300) -> str:
    """피드 요약에서 태그를 벗기고 공백을 정리한다."""
    if not text:
        return ""
    cleaned = html.unescape(_TAG_RE.sub(" ", text))
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]


def entry_published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None


def clean_title(title: str, source_site: str = "") -> str:
    """제목의 HTML 을 벗기고, 끝에 붙는 ' - 매체명' 꼬리를 떼어낸다.

    일부 매체는 제목 필드에 <span> 같은 마크업을 그대로 넣어 보낸다.
    """
    title = html.unescape(_TAG_RE.sub(" ", title or ""))
    title = " ".join(title.split())
    if source_site and title.endswith(f" - {source_site}"):
        title = title[: -len(source_site) - 3].rstrip()
    return title


def is_excluded(title: str, patterns: list[str]) -> bool:
    """부고, 인사, 정정 같은 기사 아닌 항목을 제목으로 걸러낸다."""
    return any(pattern in title for pattern in patterns)


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """종합 매체 필터. 키워드가 비면 전량 통과.

    영문 약어는 단어 경계를 요구한다. 그러지 않으면 소비자심리지수 CCSI 가
    CCS 로 잡히는 식의 오탐이 난다. 한글 키워드는 교착어라 경계를 쓰지 않는다.
    """
    if not keywords:
        return True
    haystack = text.lower()
    for keyword in keywords:
        needle = keyword.lower()
        if needle.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack):
                return True
        elif needle in haystack:
            return True
    return False


def load_config(path: Path = SOURCES_PATH) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def collect(config: dict | None = None, *, now: datetime | None = None) -> list[RawItem]:
    config = config or load_config()
    defaults = config.get("defaults", {})
    max_items = int(defaults.get("max_items_per_source", 25))
    lookback = int(defaults.get("lookback_days", 7))
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback)

    keyword_sets = {
        "ko": config.get("keywords_ko", []),
        "en": config.get("keywords_en", []),
    }
    excludes = config.get("exclude_patterns", [])

    items: list[RawItem] = []
    seen: set[str] = set()

    for source in config.get("sources", []):
        name = source["name"]
        keywords = keyword_sets.get(source.get("keywords", ""), [])
        try:
            feed = feedparser.parse(source["url"], agent=USER_AGENT)
        except Exception as exc:  # 한 소스가 죽어도 전체는 계속 돈다
            print(f"[warn] {name}: 수집 실패 ({exc})", file=sys.stderr)
            continue

        if getattr(feed, "bozo", False) and not feed.entries:
            print(f"[warn] {name}: 피드를 읽지 못했다 ({feed.get('bozo_exception')})", file=sys.stderr)
            continue

        kept = 0
        for entry in feed.entries:
            if kept >= max_items:
                break
            link = (getattr(entry, "link", "") or "").strip()
            if not link:
                continue
            published = entry_published(entry)
            # 발행일이 없는 항목은 버린다. now 로 채우면 오래된 기사가
            # 신규로 둔갑한다.
            if published is None or published < cutoff:
                continue

            title = clean_title(getattr(entry, "title", ""), name)
            if is_excluded(title, excludes):
                continue
            snippet = strip_html(getattr(entry, "summary", ""))
            if not matches_keywords(f"{title} {snippet}", keywords):
                continue

            item = RawItem(
                title=title,
                url=link,
                source=name,
                published_at=published.strftime("%Y-%m-%dT%H:%M:%SZ"),
                snippet=snippet,
            )
            if not item.title or item.id in seen:
                continue
            seen.add(item.id)
            items.append(item)
            kept += 1

        print(f"[info] {name}: {kept}건", file=sys.stderr)

    return items


if __name__ == "__main__":
    for item in collect():
        print(f"{item.published_at}  [{item.source}] {item.title}")
