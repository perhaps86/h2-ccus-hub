"""분류기 통합 테스트. 실제 API 를 부르지 않고 스텁 클라이언트로 검증한다."""

import json
import types

import anthropic
import pytest

import classify
from schema import RawItem


def _raw(n: int) -> RawItem:
    return RawItem(
        title=f"기사 {n}",
        url=f"https://example.com/{n}",
        source="테스트신문",
        published_at="2026-09-20T00:00:00Z",
        snippet="발췌",
    )


def _valid(n: int) -> dict:
    return {
        "category": "프로젝트·계약",
        "region": "국내",
        "chain": ["수소생산"],
        "importance": "중",
        "summary": f"{n}번 기사 요약.",
        "tags": ["태그"],
    }


class StubClient:
    """messages.create 만 흉내 낸다. 호출 인자와 횟수를 기록한다."""

    def __init__(self, responder):
        self.calls = []
        outer = self

        def create(**kwargs):
            outer.calls.append(kwargs)
            payload = responder(len(outer.calls), kwargs)
            block = types.SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False))
            return types.SimpleNamespace(content=[block])

        self.messages = types.SimpleNamespace(create=create)


def _echo(_call_no, kwargs):
    """요청에 들어온 항목 수만큼 정상 분류를 돌려준다."""
    count = kwargs["messages"][0]["content"].count("] 제목:")
    return {"items": [_valid(i) for i in range(count)]}


def test_빈_입력은_호출하지_않는다():
    client = StubClient(_echo)
    assert classify.classify([], client=client) == []
    assert client.calls == []


def test_배치_크기만큼_묶어서_호출한다():
    client = StubClient(_echo)
    items = [_raw(i) for i in range(classify.BATCH_SIZE * 2 + 1)]
    results = classify.classify(items, client=client)
    assert len(results) == len(items)
    assert len(client.calls) == 3  # 8 + 8 + 1


def test_모델과_스키마를_지정해_호출한다():
    client = StubClient(_echo)
    classify.classify([_raw(1)], client=client)
    kwargs = client.calls[0]
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


def test_호출_상한을_넘으면_남은_건은_미룬다(monkeypatch):
    monkeypatch.setattr(classify, "MAX_CALLS_PER_RUN", 1)
    client = StubClient(_echo)
    items = [_raw(i) for i in range(classify.BATCH_SIZE * 3)]
    results = classify.classify(items, client=client)
    assert len(client.calls) == 1
    assert len(results) == classify.BATCH_SIZE


def test_API_오류가_나도_나머지_배치는_계속_처리한다():
    def responder(call_no, kwargs):
        if call_no == 1:
            raise anthropic.APIError("boom", request=None, body=None)
        return _echo(call_no, kwargs)

    client = StubClient(responder)
    items = [_raw(i) for i in range(classify.BATCH_SIZE * 2)]
    results = classify.classify(items, client=client)
    assert len(client.calls) == 2
    assert len(results) == classify.BATCH_SIZE  # 첫 배치는 버려지고 둘째만 남는다


def test_허용값을_벗어난_응답은_격리된다():
    def responder(_call_no, _kwargs):
        return {"items": [_valid(0) | {"importance": "매우상"}]}

    client = StubClient(responder)
    results = classify.classify([_raw(1)], client=client)
    assert len(results) == 1
    assert results[0].needs_review is True


def test_응답_개수가_모자라도_짝지어진_만큼만_남긴다():
    def responder(_call_no, _kwargs):
        return {"items": [_valid(0)]}

    client = StubClient(responder)
    results = classify.classify([_raw(1), _raw(2), _raw(3)], client=client)
    assert len(results) == 1


def test_프롬프트에_기사_본문_복제_금지가_들어있다():
    assert "그대로 옮기지" in classify.SYSTEM_PROMPT
    assert "지어내지" in classify.SYSTEM_PROMPT
