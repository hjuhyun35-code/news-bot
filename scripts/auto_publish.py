"""
완성된 초안을 텔레그램으로 보내 올릴지 물어본다.

    python scripts/auto_publish.py cardiff-giant

**여기서는 발행하지 않는다.** 사람이 단추를 누른 뒤 check_approvals 나
telegram_command 가 올린다. 2026-08-06, 사장님이 "전부 단추로" 라고
정하셨다 — 예약 실행이 만든 것도 사람이 봐야 나간다.

그래서 안 누르면 안 올라간다. 그게 이 방식의 대가다.

독자 반응과 사실 검증은 그대로 돌린다. 막지는 않고, 무엇이 걸렸는지를
단추 바로 위에 적어 보낸다. 문제가 있는 줄 알면서 누르는 것과 모르고
누르는 것은 다르다. 적어 보내는 것들:

  1. 자료와 모순되는 주장    — 사실이 틀린 것. 올리면 되돌릴 수 없다
  2. 독자 전원이 그냥 넘김   — 올려도 아무도 안 본다
  3. 평균이 너무 낮음        — 계정 인상을 깎는다

"근거 없음"은 세지 않는다. 자료에 없다는 뜻이지 틀렸다는 뜻이 아니고,
세기 시작하면 거의 모든 게시물이 걸린다. 대신 요약에 적는다.
"""

import json
import os
import sys

import telegram

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIN_SCORE = 4.0      # 평균이 이보다 낮으면 사람에게 넘긴다
MIN_READERS = 2      # 반응이 이보다 적으면 판단 근거가 부족하다


def load(post_dir, name, default=None):
    path = os.path.join(post_dir, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def judge(readers, check):
    """(올려도 되는가, 사람에게 넘기는 이유들)"""
    stop = []

    if not readers or readers.get("asked", 0) < MIN_READERS:
        stop.append("독자 반응을 충분히 못 받았습니다")
        return False, stop

    bad = [c for c in (check or {}).get("claims", [])
           if c["verdict"] == "contradicted"]
    for c in bad:
        stop.append(f"자료와 모순: {c['where']} — {c['claim'][:80]}")

    if readers["read_through"] == 0:
        stop.append(f"{readers['asked']}명 전원이 끝까지 안 봤습니다")

    if readers["average"] < MIN_SCORE:
        stop.append(f"독자 평균 {readers['average']}점 (기준 {MIN_SCORE}점)")

    return not stop, stop


def summary(slug, readers, check):
    lines = [f"<b>{slug}</b>"]
    if readers:
        lines.append(f"독자 {readers['average']}점 · "
                     f"{readers['asked']}명 중 {readers['read_through']}명 끝까지 봄")
        for r in readers["readers"]:
            lines.append(f"· {r['name']}({r['age']}) {r['score']}점 — {r['bad'][:90]}")

    weak = [c for c in (check or {}).get("claims", [])
            if c["verdict"] != "supported"]
    if weak:
        lines.append("")
        lines.append(f"⚠️ 자료로 확인 안 되는 주장 {len(weak)}개")
        for c in weak[:4]:
            lines.append(f"· {c['where']}: {c['claim'][:90]}")
    return lines


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/auto_publish.py <슬러그>")
    slug = sys.argv[1]

    post_dir = os.path.join(ROOT, "posts", slug)
    if load(post_dir, "published.json"):
        print("이미 올라간 글입니다. 아무것도 하지 않습니다.")
        return

    readers = load(post_dir, "readers.json")
    check = load(post_dir, "check.json")
    ok, stop = judge(readers, check)

    lines = summary(slug, readers, check)
    unfixed = load(post_dir, "unfixed.json")
    if unfixed:
        lines.append("")
        lines.append("⚠️ 사진을 못 알아보겠다는데 코드가 못 고친 카드")
        for c in unfixed["cards"]:
            lines.append(f"· {c}")

    if ok:
        head = [f"📮 <b>{slug}</b> — 올릴까요?", "",
                "독자 관문은 통과했습니다."]
        print("독자 관문 통과. 단추를 보냅니다.")
    else:
        head = [f"🤔 <b>{slug}</b> — 올릴까요?", ""] + [f"· {s}" for s in stop]
        print("관문에 걸렸습니다. 단추를 보냅니다:")
        for s in stop:
            print(f"  - {s}")

    telegram.say("\n".join(head + [""] + lines[1:]),
                 buttons=[[("✅ 올려줘", f"ok:{slug}"),
                           ("🗑 버리기", f"no:{slug}")],
                          [("🎬 릴스 만들기", f"reel:{slug}")]])


if __name__ == "__main__":
    main()
