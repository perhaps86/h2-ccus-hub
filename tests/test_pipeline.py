import types
from datetime import datetime, timezone

import pytest

import collect
import merge
from schema import (
    RawItem,
    ValidationError,
    build_news_item,
    make_id,
    normalize_url,
)


# ── URL 정규화와 중복 판정 ────────────────────────────────

@pytest.mark.parametrize(
    "a,b",
    [
        ("https://example.com/news/1", "https://example.com/news/1/"),
        ("https://example.com/news/1", "https://WWW.Example.com/news/1"),
        ("https://example.com/n?a=1&b=2", "https://example.com/n?b=2&a=1"),
        ("https://example.com/n", "https://example.com/n?utm_source=rss"),
        ("https://example.com/n", "https://example.com/n#section"),
    ],
)
def test_같은_기사는_같은_id를_갖는다(a, b):
    assert normalize_url(a) == normalize_url(b)
    assert make_id(a) == make_id(b)


def test_다른_기사는_다른_id를_갖는다():
    assert make_id("https://example.com/a") != make_id("https://example.com/b")


# ── 분류 결과 검증 ────────────────────────────────────────

def _raw():
    return RawItem(
        title="울산 부생수소 설비 증설",
        url="https://example.com/article",
        source="테스트신문",
        published_at="2026-09-20T00:00:00Z",
    )


def _valid_classification():
    return {
        "category": "프로젝트·계약",
        "region": "국내",
        "chain": ["수소생산"],
        "importance": "상",
        "summary": "울산에 부생수소 설비를 증설한다는 내용이다.",
        "tags": ["울산"],
    }


def test_정상_분류는_통과한다():
    item = build_news_item(_raw(), _valid_classification())
    assert item.needs_review is False
    assert item.category == "프로젝트·계약"
    assert item.chain == ["수소생산"]


def test_허용값을_벗어난_분류는_격리된다():
    bad = _valid_classification() | {"category": "아무거나"}
    item = build_news_item(_raw(), bad)
    assert item.needs_review is True
    assert "category" in item.review_reason


def test_빈_요약은_격리된다():
    bad = _valid_classification() | {"summary": "   "}
    item = build_news_item(_raw(), bad)
    assert item.needs_review is True


def test_허용값_밖의_chain은_걸러진다():
    bad = _valid_classification() | {"chain": ["수소생산", "우주항공"]}
    item = build_news_item(_raw(), bad)
    assert item.chain == ["수소생산"]


def test_긴_요약은_잘린다():
    bad = _valid_classification() | {"summary": "가" * 600}
    item = build_news_item(_raw(), bad)
    assert len(item.summary) <= 403
    assert item.summary.endswith("...")


def test_strict_모드는_예외를_올린다():
    with pytest.raises(ValidationError):
        build_news_item(_raw(), _valid_classification() | {"region": "달"}, strict=True)


# ── 병합과 보존기간 ───────────────────────────────────────

def test_이미_아는_항목은_다시_분류하지_않는다():
    items = [_raw()]
    assert merge.select_new(items, known_ids=set()) == items
    assert merge.select_new(items, known_ids={items[0].id}) == []


def test_같은_실행_안의_중복도_제거된다():
    dup = [_raw(), _raw()]
    assert len(merge.select_new(dup, known_ids=set())) == 1


def test_보존기간이_지난_항목은_분리된다():
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    items = [
        {"id": "a", "published_at": "2026-09-01T00:00:00Z"},
        {"id": "b", "published_at": "2025-01-01T00:00:00Z"},
    ]
    keep, expired = merge.partition_expired(items, now=now)
    assert [i["id"] for i in keep] == ["a"]
    assert [i["id"] for i in expired] == ["b"]


def test_발행일이_깨진_항목은_버리지_않는다():
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    keep, expired = merge.partition_expired([{"id": "x", "published_at": "???"}], now=now)
    assert [i["id"] for i in keep] == ["x"]
    assert expired == []


def test_병합_결과는_최신순으로_정렬된다(tmp_path, monkeypatch):
    monkeypatch.setattr(merge, "NEWS_PATH", tmp_path / "news.json")
    monkeypatch.setattr(merge, "ARCHIVE_PATH", tmp_path / "archive.json")

    old = build_news_item(
        RawItem("옛 기사", "https://example.com/old", "s", "2026-09-01T00:00:00Z"),
        _valid_classification(),
    )
    new = build_news_item(
        RawItem("새 기사", "https://example.com/new", "s", "2026-09-22T00:00:00Z"),
        _valid_classification(),
    )
    payload = merge.merge([old, new], now=datetime(2026, 9, 23, tzinfo=timezone.utc))
    assert [i["title"] for i in payload["items"]] == ["새 기사", "옛 기사"]
    assert payload["count"] == 2


# ── 수집 유틸 ─────────────────────────────────────────────

def test_HTML_태그와_공백을_정리한다():
    assert collect.strip_html("<p>수소   <b>계약</b></p>") == "수소 계약"


def test_제목의_매체명_꼬리를_뗀다():
    assert collect.clean_title("울산 수소 증설 - 테스트신문", "테스트신문") == "울산 수소 증설"
    assert collect.clean_title("울산 수소 증설", "테스트신문") == "울산 수소 증설"


def test_키워드가_비면_전량_통과한다():
    assert collect.matches_keywords("아무 기사", []) is True


def test_키워드_필터는_제목과_발췌를_함께_본다():
    assert collect.matches_keywords("액화천연가스 도입 확대", ["수소", "암모니아"]) is False
    assert collect.matches_keywords("울산 부생수소 공급", ["수소"]) is True


def test_키워드_필터는_대소문자를_가리지_않는다():
    assert collect.matches_keywords("Carbon Capture deal signed", ["carbon capture"]) is True


def _fake_feed(entries):
    return types.SimpleNamespace(entries=entries, bozo=False, get=lambda *_: None)


def _entry(title, link, parsed=None, summary=""):
    entry = types.SimpleNamespace(title=title, link=link, summary=summary)
    if parsed is not None:
        entry.published_parsed = parsed
    return entry


def _config(**source):
    base = {"name": "테스트피드", "url": "https://feed.example/rss"}
    return {"defaults": {"max_items_per_source": 10, "lookback_days": 7},
            "sources": [base | source]}


def test_발행일이_없는_항목은_버린다(monkeypatch):
    # 발행일 없는 항목을 수집 시각으로 채우면 오래된 기사가 신규로 둔갑한다.
    monkeypatch.setattr(
        collect.feedparser, "parse",
        lambda *a, **k: _fake_feed([_entry("날짜 없는 수소 기사", "https://x.test/1")]),
    )
    assert collect.collect(_config()) == []


def test_조회기간보다_오래된_항목은_버린다(monkeypatch):
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    monkeypatch.setattr(
        collect.feedparser, "parse",
        lambda *a, **k: _fake_feed([
            _entry("최근 수소 기사", "https://x.test/new", (2026, 9, 22, 0, 0, 0)),
            _entry("2022년 수소 기사", "https://x.test/old", (2022, 9, 22, 0, 0, 0)),
        ]),
    )
    items = collect.collect(_config(), now=now)
    assert [i.title for i in items] == ["최근 수소 기사"]


def test_소스의_키워드_설정이_적용된다(monkeypatch):
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    monkeypatch.setattr(
        collect.feedparser, "parse",
        lambda *a, **k: _fake_feed([
            _entry("도시가스 요금 인상", "https://x.test/a", (2026, 9, 22, 0, 0, 0)),
            _entry("부생수소 공급 계약", "https://x.test/b", (2026, 9, 22, 0, 0, 0)),
        ]),
    )
    config = _config(keywords="ko") | {"keywords_ko": ["수소"]}
    items = collect.collect(config, now=now)
    assert [i.title for i in items] == ["부생수소 공급 계약"]


def test_기사가_아닌_제목은_제외된다():
    patterns = ["바로잡습니다", "[부고]"]
    assert collect.is_excluded("[바로잡습니다]", patterns) is True
    assert collect.is_excluded("[부고] 아무개 별세", patterns) is True
    assert collect.is_excluded("울산 수소 증설", patterns) is False


def test_영문_약어는_단어_경계를_요구한다():
    # 소비자심리지수 CCSI 가 CCS 로 잡히면 안 된다.
    assert collect.matches_keywords("9월 소비자심리 반등…CCSI 106.6", ["CCS"]) is False
    assert collect.matches_keywords("정부, CCS 실증사업 착수", ["CCS"]) is True
    assert collect.matches_keywords("hydrogenation catalyst study", ["hydrogen"]) is False


def test_제목의_HTML_마크업을_벗긴다():
    raw = '<span class="title-top">[인터뷰] 부원장</span><br />“수소, 에너지 전환의 축”'
    assert collect.clean_title(raw) == '[인터뷰] 부원장 “수소, 에너지 전환의 축”'


def test_빈_chain은_도메인_밖으로_기록된다():
    item = build_news_item(_raw(), _valid_classification() | {"chain": []})
    assert item.needs_review is True
    assert "도메인 밖" in item.review_reason
    assert item.chain == []  # 없는 단계를 임의로 채우지 않는다


def test_허용값_밖_chain은_오분류로_기록된다():
    item = build_news_item(_raw(), _valid_classification() | {"chain": ["우주항공"]})
    assert item.needs_review is True
    assert "허용값" in item.review_reason
