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
    """구글뉴스 제목 끝의 ' - 매체명' 꼬리를 떼어낸다."""
    title = " ".join(html.unescape(title or "").split())
    if source_site and title.endswith(f" - {source_site}"):
        title = title[: -len(source_site) - 3].rstrip()
    return title


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

    items: list[RawItem] = []
    seen: set[str] = set()

    for source in config.get("sources", []):
        name = source["name"]
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
            if published and published < cutoff:
                continue

            site = ""
            src = getattr(entry, "source", None)
            if src is not None:
                site = getattr(src, "title", "") or ""

            item = RawItem(
                title=clean_title(getattr(entry, "title", ""), site),
                url=link,
                source=site or name,
                published_at=(published or now).strftime("%Y-%m-%dT%H:%M:%SZ"),
                snippet=strip_html(getattr(entry, "summary", "")),
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
