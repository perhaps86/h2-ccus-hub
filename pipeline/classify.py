"""Claude Haiku 로 뉴스를 분류하고 요약한다.

설계 원칙
  - 신규 항목만 호출한다. 이미 분류된 것은 다시 부르지 않는다.
  - 한 번 실행에서 호출 건수 상한을 둔다. 피드가 폭주해도 비용이 튀지 않는다.
  - 모델 출력은 schema.build_news_item 의 검증을 거친다. 허용값을 벗어나면
    needs_review 로 격리되고 사이트에는 실리지 않는다.
  - 요약은 기사 본문 복제가 아니라 자체 문장이어야 한다. 프롬프트에 명시한다.
"""

from __future__ import annotations

import json
import os
import sys

import anthropic

from schema import (
    CATEGORIES,
    CHAIN_STAGES,
    IMPORTANCE,
    REGIONS,
    NewsItem,
    RawItem,
    build_news_item,
)

MODEL = "claude-haiku-4-5"
MAX_CALLS_PER_RUN = int(os.getenv("H2HUB_MAX_CALLS", "60"))
BATCH_SIZE = 8  # 한 번의 호출에 여러 건을 담아 토큰 오버헤드를 줄인다

SYSTEM_PROMPT = f"""너는 수소·암모니아·CCUS 산업 뉴스를 분류하는 애널리스트다.
입력으로 기사 제목과 짧은 발췌를 받는다. 각 기사에 대해 아래를 판정한다.

category: {" / ".join(CATEGORIES)} 중 하나
region: {" / ".join(REGIONS)} 중 하나 (기사에서 다루는 사업의 소재지 기준)
chain: {" / ".join(CHAIN_STAGES)} 중 해당하는 것 전부 (배열)
  수소·암모니아·CCUS 와 무관한 기사면 빈 배열로 둬라. 억지로 채우지 마라.
importance: {" / ".join(IMPORTANCE)}
  상 = 투자 결정, 대형 계약, 제도 확정처럼 사업 판단을 바꾸는 사안
  중 = 사업 진행 상황, 기술 실증, 주요 기업 동향
  하 = 행사, 단순 언급, 홍보성 기사
summary: 한국어 2~3문장. 제목만으로 알 수 없는 정보를 담고, 왜 의미가 있는지 한 줄을 붙인다.
tags: 핵심 고유명사 최대 4개 (기업명, 지역, 제도명)

규칙
- summary 는 기사 문장을 그대로 옮기지 말고 네 문장으로 다시 써라.
- 발췌에 없는 수치나 사실을 지어내지 마라. 확실하지 않으면 쓰지 마라.
- 수소·암모니아·CCUS 와 무관한 기사는 chain 을 빈 배열로, importance 를 "하"로 둬라.

출력은 JSON 배열 하나. 입력 순서와 같은 개수, 같은 순서로 반환한다."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "region": {"type": "string", "enum": list(REGIONS)},
                    "chain": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(CHAIN_STAGES)},
                    },
                    "importance": {"type": "string", "enum": list(IMPORTANCE)},
                    "summary": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["category", "region", "chain", "importance", "summary", "tags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _render_batch(batch: list[RawItem]) -> str:
    lines = []
    for idx, item in enumerate(batch, start=1):
        lines.append(f"[{idx}] 제목: {item.title}")
        lines.append(f"    출처: {item.source}")
        if item.snippet:
            lines.append(f"    발췌: {item.snippet}")
    return "\n".join(lines)


def _call(client: anthropic.Anthropic, batch: list[RawItem]) -> list[dict]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _render_batch(batch)}],
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    )
    text = next(block.text for block in response.content if block.type == "text")
    parsed = json.loads(text)
    return parsed.get("items", [])


def classify(items: list[RawItem], *, client: anthropic.Anthropic | None = None) -> list[NewsItem]:
    """RawItem 목록을 NewsItem 목록으로 바꾼다.

    호출 상한을 넘는 분량은 이번 실행에서 처리하지 않는다. 다음 실행이
    남은 것을 집어간다(수집은 멱등이라 다시 잡힌다).
    """
    if not items:
        return []

    client = client or anthropic.Anthropic()
    results: list[NewsItem] = []
    calls = 0

    for start in range(0, len(items), BATCH_SIZE):
        if calls >= MAX_CALLS_PER_RUN:
            remaining = len(items) - start
            print(f"[info] 호출 상한({MAX_CALLS_PER_RUN})에 도달. {remaining}건은 다음 실행으로 미룬다.",
                  file=sys.stderr)
            break

        batch = items[start : start + BATCH_SIZE]
        calls += 1
        try:
            classifications = _call(client, batch)
        except anthropic.APIError as exc:
            print(f"[warn] 분류 호출 실패({exc}). {len(batch)}건은 보류한다.", file=sys.stderr)
            continue

        if len(classifications) != len(batch):
            print(f"[warn] 응답 개수 불일치: 요청 {len(batch)}, 응답 {len(classifications)}",
                  file=sys.stderr)

        for raw, classification in zip(batch, classifications):
            results.append(build_news_item(raw, classification))

    flagged = sum(1 for item in results if item.needs_review)
    print(f"[info] 분류 완료: {len(results)}건 (호출 {calls}회, 보류 {flagged}건)", file=sys.stderr)
    return results
