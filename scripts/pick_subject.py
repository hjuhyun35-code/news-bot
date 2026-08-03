"""
queue.json 에서 다음에 만들 소재 하나를 고른다.

    python scripts/pick_subject.py          다음 소재의 슬러그를 출력
    python scripts/pick_subject.py --list   목록 전체와 상태를 표시

"만들었는지"는 파일을 보고 판단한다. posts/<slug>/post.json 이 있으면
만든 것이다. 목록 파일에 상태를 기록하지 않는 이유는, 기록해두면
자동 실행이 도중에 죽었을 때 목록과 실제가 어긋나기 때문이다.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "queue.json")


def load():
    if not os.path.exists(QUEUE):
        sys.exit("[실패] queue.json 이 없습니다.")
    with open(QUEUE, encoding="utf-8") as f:
        return json.load(f)["subjects"]


def state(item):
    """이 소재가 지금 어디까지 왔는지."""
    if item.get("hold"):
        return "보류"
    d = os.path.join(ROOT, "posts", item["slug"])
    if os.path.exists(os.path.join(d, "post.json")):
        return "완성"
    if os.path.exists(os.path.join(d, "source.json")):
        return "사진있음"
    return "대기"


def main():
    subjects = load()

    if "--list" in sys.argv:
        for item in subjects:
            print(f"  {state(item):5}  {item['slug']:16}  {item.get('hook', '')}")
        done = sum(1 for i in subjects if state(i) == "완성")
        print()
        print(f"전체 {len(subjects)}개 중 {done}개 완성, "
              f"{sum(1 for i in subjects if state(i) == '대기')}개 대기")
        return

    for item in subjects:
        if state(item) in ("대기", "사진있음"):
            # 자동 실행이 이 한 줄을 받아 다음 단계로 넘긴다
            print(item["slug"])
            return

    sys.exit("[중단] 만들 소재가 남지 않았습니다. queue.json 에 더 넣어주세요.")


if __name__ == "__main__":
    main()
