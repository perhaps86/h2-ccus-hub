"""수집 → 분류 → 병합의 진입점.

멱등성이 이 파일의 핵심이다. 같은 날 몇 번을 돌려도 결과가 같아야
실패했을 때 그냥 다시 돌리면 된다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collect import collect, load_config
from schema import NewsItem, RawItem

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NEWS_PATH = DATA_DIR / "news.json"
ARCHIVE_PATH = DATA_DIR / "archive.json"
RETENTION_DAYS = 180


def load_news(path: Path | None = None) -> dict:
    # 기본 경로는 호출 시점에 읽는다. import 시점에 묶어두면 테스트에서
    # 경로를 갈아끼울 수 없고, 실수로 실제 데이터 파일을 건드리게 된다.
    path = path or NEWS_PATH
    if not path.exists():
        return {"generated_at": None, "items": []}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")


def select_new(raw_items: list[RawItem], known_ids: set[str]) -> list[RawItem]:
    """이미 아는 id 는 버린다. 같은 실행 안의 중복도 제거한다."""
    seen: set[str] = set()
    fresh: list[RawItem] = []
    for item in raw_items:
        if item.id in known_ids or item.id in seen:
            continue
        seen.add(item.id)
        fresh.append(item)
    return fresh


def partition_expired(items: list[dict], *, now: datetime, days: int = RETENTION_DAYS):
    """보존기간이 지난 항목을 분리한다."""
    cutoff = now - timedelta(days=days)
    keep, expired = [], []
    for item in items:
        try:
            published = datetime.strptime(item["published_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except (KeyError, ValueError):
            keep.append(item)
            continue
        (expired if published < cutoff else keep).append(item)
    return keep, expired


def merge(new_items: list[NewsItem], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    current = load_news()
    items = list(current.get("items", []))

    known = {item["id"] for item in items}
    items.extend(item.to_dict() for item in new_items if item.id not in known)

    items, expired = partition_expired(items, now=now)
    items.sort(key=lambda item: item.get("published_at", ""), reverse=True)

    if expired:
        archive = load_news(ARCHIVE_PATH)
        archive_items = list(archive.get("items", []))
        archive_ids = {item["id"] for item in archive_items}
        archive_items.extend(item for item in expired if item["id"] not in archive_ids)
        save_json(ARCHIVE_PATH, {
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "items": archive_items,
        })

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(items),
        "items": items,
    }


def run(*, dry_run: bool = False, limit: int | None = None) -> int:
    config = load_config()
    raw_items = collect(config)
    known = {item["id"] for item in load_news().get("items", [])}
    fresh = select_new(raw_items, known)

    if limit is not None:
        fresh = fresh[:limit]

    print(f"[info] 수집 {len(raw_items)}건 중 신규 {len(fresh)}건", file=sys.stderr)

    if not fresh:
        print("[info] 새 항목이 없다. 파일을 건드리지 않는다.", file=sys.stderr)
        return 0

    if dry_run:
        for item in fresh:
            print(f"  - [{item.source}] {item.title}")
        return 0

    from classify import classify  # API 키가 필요한 시점까지 import 를 미룬다

    classified = classify(fresh)
    if not classified:
        print("[warn] 분류 결과가 없다. 파일을 건드리지 않는다.", file=sys.stderr)
        return 1

    payload = merge(classified)
    save_json(NEWS_PATH, payload)
    print(f"[info] 저장 완료: 총 {payload['count']}건", file=sys.stderr)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="수소·암모니아·CCUS 뉴스 수집 파이프라인")
    parser.add_argument("--dry-run", action="store_true", help="분류 없이 신규 항목만 출력")
    parser.add_argument("--limit", type=int, default=None, help="이번 실행에서 처리할 신규 항목 수 상한")
    args = parser.parse_args()
    raise SystemExit(run(dry_run=args.dry_run, limit=args.limit))
