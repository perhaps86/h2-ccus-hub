"""데이터 모델과 검증.

이 파이프라인은 외부 LLM 출력을 신뢰하지 않는다. 분류 결과는 여기 정의된
허용값 안에 들어와야만 사이트에 실린다. 벗어나면 needs_review 로 격리한다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# 필터 축. 사이트의 3축 필터와 1:1로 대응한다.
CATEGORIES = ("정책·규제", "프로젝트·계약", "투자·금융", "기술", "시장·가격")
REGIONS = ("국내", "해외")
CHAIN_STAGES = ("수소생산", "암모니아", "CCUS", "운송·저장", "활용")
IMPORTANCE = ("상", "중", "하")

# 추적에서 제거할 쿼리 파라미터. 같은 기사가 다른 URL로 들어오는 걸 막는다.
_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|igshid$|ref$|ref_src$|spm$)")

MAX_SUMMARY_CHARS = 400


def normalize_url(url: str) -> str:
    """중복 판정용 URL 정규화.

    스킴·호스트를 소문자로 맞추고, 추적 파라미터와 프래그먼트를 버리고,
    남은 쿼리는 정렬한다. 끝의 슬래시도 제거한다.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING_PARAMS.match(k)
        )
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def make_id(url: str) -> str:
    """정규화 URL의 해시. 같은 기사면 언제 돌려도 같은 id가 나온다."""
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:16]


class ValidationError(ValueError):
    pass


@dataclass
class RawItem:
    """수집 직후, 분류 전 항목. 기사 본문은 담지 않는다."""

    title: str
    url: str
    source: str
    published_at: str  # ISO8601 (UTC)
    snippet: str = ""  # 피드가 준 짧은 발췌. 분류 입력용이며 저장하지 않는다.

    @property
    def id(self) -> str:
        return make_id(self.url)


@dataclass
class NewsItem:
    """사이트에 실리는 최종 항목."""

    id: str
    title: str
    url: str
    source: str
    published_at: str
    category: str
    region: str
    chain: list[str]
    importance: str
    summary: str
    collected_at: str
    needs_review: bool = False
    review_reason: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _fail(reason: str, strict: bool) -> str:
    if strict:
        raise ValidationError(reason)
    return reason


def build_news_item(raw: RawItem, classification: dict, *, strict: bool = False) -> NewsItem:
    """LLM 분류 결과를 검증해 NewsItem 으로 만든다.

    strict=False 이면 위반을 예외로 올리지 않고 needs_review 로 표시한다.
    사이트는 needs_review 항목을 렌더링하지 않으므로, 오분류가 그대로
    공개되는 일이 없다.
    """
    problems: list[str] = []

    category = str(classification.get("category", "")).strip()
    if category not in CATEGORIES:
        problems.append(_fail(f"category 허용값 아님: {category!r}", strict))
        category = CATEGORIES[0]

    region = str(classification.get("region", "")).strip()
    if region not in REGIONS:
        problems.append(_fail(f"region 허용값 아님: {region!r}", strict))
        region = REGIONS[1]

    raw_chain = classification.get("chain") or []
    if isinstance(raw_chain, str):
        raw_chain = [raw_chain]
    chain = [c for c in (str(x).strip() for x in raw_chain) if c in CHAIN_STAGES]
    if not chain:
        problems.append(_fail(f"chain 이 비었거나 허용값 아님: {raw_chain!r}", strict))

    importance = str(classification.get("importance", "")).strip()
    if importance not in IMPORTANCE:
        problems.append(_fail(f"importance 허용값 아님: {importance!r}", strict))
        importance = "중"

    summary = " ".join(str(classification.get("summary", "")).split())
    if not summary:
        problems.append(_fail("summary 가 비었음", strict))
    elif len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS].rstrip() + "..."

    tags = [str(t).strip() for t in (classification.get("tags") or []) if str(t).strip()][:6]

    return NewsItem(
        id=raw.id,
        title=raw.title.strip(),
        url=raw.url.strip(),
        source=raw.source.strip(),
        published_at=raw.published_at,
        category=category,
        region=region,
        chain=chain or [CHAIN_STAGES[0]],
        importance=importance,
        summary=summary,
        collected_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        needs_review=bool(problems),
        review_reason="; ".join(p for p in problems if p),
        tags=tags,
    )
