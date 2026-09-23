# 수소 · 암모니아 · CCUS 인텔리전스

국내외 공개 뉴스를 매일 자동으로 수집하고, 사업 판단에 쓰는 축으로 분류해 공개하는 사이트입니다.

**사이트**: https://perhaps86.github.io/h2-ccus-hub/

## 왜 만들었나

수소·암모니아·CCUS 사업을 검토할 때 정작 필요한 것은 기사 목록이 아니라,
"이 소식이 사업 구조의 어느 지점을 건드리는가"입니다. 그래서 세 가지를 지키려고 했습니다.

- 뉴스를 **밸류체인 단계와 의사결정 유형**으로 나눈다. 생산인지 저장인지, 제도 변화인지 투자 결정인지.
- 자동으로 모으되 **판단은 사람이 한다.** 분류와 요약은 기계가, 주간 코멘트는 직접 씁니다.
- **검증을 통과하지 못한 자동 분류는 공개하지 않는다.**

## 동작 방식

```
GitHub Actions (매일 07:00 KST)
  │
  ├─ collect.py    sources.yaml 의 RSS 에서 제목·링크·출처·발행일 수집
  │                (기사 본문은 저장하지 않음)
  ├─ merge.py      정규화 URL 기준 중복 제거 → 신규 항목만 추출
  ├─ classify.py   Claude Haiku 로 분류·요약 (신규 항목만, 호출 상한 적용)
  ├─ schema.py     허용값 검증. 벗어나면 needs_review 로 격리
  └─ merge.py      data/news.json 병합, 180일 경과분은 archive.json 으로
        │
        └─ 변경분 커밋 → GitHub Pages 재배포
```

### 설계 결정

| 결정 | 이유 |
|---|---|
| 기사 본문을 저장하지 않는다 | 제목·링크·출처와 자체 요약만 보관합니다. 원문을 들고 있지 않으면 저작권 문제가 생기지 않습니다. |
| LLM 출력을 검증한 뒤 반영한다 | 분류값이 정의된 목록을 벗어나거나 요약이 비면 `needs_review` 로 표시하고 화면에 띄우지 않습니다. 자동화가 오분류를 그대로 공개하지 않게 하는 장치입니다. |
| 같은 날 여러 번 돌려도 결과가 같다 | URL 을 정규화해 id 를 만들기 때문에 재실행이 안전합니다. 실패하면 그냥 다시 돌리면 됩니다. |
| 신규 항목만 모델에 보낸다 | 이미 분류한 기사는 다시 부르지 않습니다. 여기에 실행당 호출 상한을 더해 비용이 튀지 않게 했습니다. |
| 소스 목록을 설정 파일로 분리했다 | `pipeline/sources.yaml` 만 고치면 수집 대상이 바뀝니다. 다른 도메인으로 옮길 때 코드를 건드릴 필요가 없습니다. |

## 로컬 실행

```bash
pip install -r requirements.txt

python -m pytest -q                      # 테스트
python pipeline/merge.py --dry-run       # 수집만, 분류 없음 (API 키 불필요)
export ANTHROPIC_API_KEY=...             # 분류에 필요
python pipeline/merge.py --limit 8       # 신규 8건만 처리
python -m http.server 8000               # 사이트 확인 → http://localhost:8000
```

## 저장소 구조

```
index.html              화면
assets/style.css        스타일 (라이트·다크)
assets/app.js           필터와 렌더링 (프레임워크 없음)
data/news.json          수록 데이터
data/insights.json      주간 코멘트 (직접 작성)
pipeline/sources.yaml   수집 소스 목록
pipeline/collect.py     RSS 수집
pipeline/classify.py    분류·요약
pipeline/schema.py      데이터 모델과 검증
pipeline/merge.py       진입점, 중복 제거와 병합
tests/                  pytest
```

## 데이터 형식

```json
{
  "id": "정규화 URL 의 해시",
  "title": "기사 제목",
  "url": "원문 링크",
  "source": "매체",
  "published_at": "2026-09-22T00:00:00Z",
  "category": "정책·규제 | 프로젝트·계약 | 투자·금융 | 기술 | 시장·가격",
  "region": "국내 | 해외",
  "chain": ["수소생산", "암모니아", "CCUS", "운송·저장", "활용"],
  "importance": "상 | 중 | 하",
  "summary": "자체 생성 요약",
  "tags": ["고유명사"],
  "needs_review": false
}
```

## 한계

- 요약은 자동 생성이며 원문을 대체하지 않습니다. 반드시 원문을 확인하세요.
- 수집원은 공개 뉴스이므로 보도되지 않은 사안은 잡히지 않습니다.
- 회의나 보고 직전에는 해당 기업 공시와 규제기관 발표로 다시 확인하시기 바랍니다.
- 개인이 운영하며 특정 기업의 입장을 대변하지 않습니다.

## 운영

- 조훈희 · 수소 · 암모니아 · CCUS 사업개발 16년차
- 이슈와 소스 추가 제안은 GitHub Issues 로 받습니다.
