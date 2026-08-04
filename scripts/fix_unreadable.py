"""
독자들이 "사진을 못 알아보겠다"고 지목한 카드를 통째 보기로 바꾸고 다시 그린다.

    python scripts/fix_unreadable.py cardiff-giant

readers.json 의 unreadable 목록을 읽는다. 다섯 명 중 셋 이상이 같은 카드를
지목했을 때만 목록에 오른다. 한 명의 취향이 아니라 여러 사람이 같은 것을
못 본다면 그건 결함이다.

왜 이 방식인가.

대본 쪽에 "가로로 긴 사진은 통째로 보여줘라"고 지시했지만 한 번도 고르지
않았다. 오늘 같은 일이 다섯 번 있었다 — 캡션 길이, 출처 형식, 카드 개수,
확대 배율, 그리고 이것. 프롬프트로 부탁한 것은 대체로 지켜지지 않는다.

그런데 이 건은 코드가 혼자 판단할 수 없다. "이 사진이 알아볼 수 있는가"는
자르기 비율이나 화면 비로 계산되지 않는다. 어떤 확대는 좋은 세부 컷이고
어떤 확대는 얼룩이다. 그래서 사람이 보는 자리 — 독자 다섯 명 — 를 판정에
쓰고, 고치는 일만 코드가 한다.
"""

import json
import os
import shutil
import sys
import tempfile

import render_cards

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/fix_unreadable.py <슬러그>")
    slug = sys.argv[1]

    post_dir = os.path.join(ROOT, "posts", slug)
    readers_path = os.path.join(post_dir, "readers.json")
    if not os.path.exists(readers_path):
        print("독자 반응이 없습니다. 넘어갑니다.")
        return

    with open(readers_path, encoding="utf-8") as f:
        unreadable = json.load(f).get("unreadable", [])
    if not unreadable:
        print("못 알아보겠다는 카드 없음")
        return

    post_path = os.path.join(post_dir, "post.json")
    with open(post_path, encoding="utf-8") as f:
        post = json.load(f)

    cards = post["cards"]
    changed = []
    for n in unreadable:
        if not 1 <= n <= len(cards):
            continue
        card = cards[n - 1]
        if card.get("fit") == "whole":
            # 이미 통째로 보여주는데도 못 알아본다면 사진 자체가 문제다.
            # 여기서 더 할 수 있는 것이 없으니 사람이 보게 남긴다.
            print(f"  카드 {n}: 이미 통째 보기입니다. 사진 자체를 바꿔야 합니다")
            continue
        card["fit"] = "whole"
        changed.append(n)
        print(f"  카드 {n}: 잘라 넣기 → 통째 보기")

    if not changed:
        return

    with open(post_path, "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)

    img_dir = os.path.join(post_dir, post.get("image_dir", "img"))
    handle = post.get("handle", "@theglassnegative")
    browser = render_cards.find_browser()
    tmp = tempfile.mkdtemp(dir=ROOT, prefix=".fix-")
    try:
        for n in changed:
            out = os.path.join(post_dir, f"card{n}.png")
            kb = render_cards.shoot(
                render_cards.build_html(cards[n - 1], img_dir, handle,
                                        n, len(cards)),
                out, browser, tmp)
            if kb < 60:
                sys.exit(f"[실패] 카드 {n} 이 {kb} KB 뿐입니다.")
            print(f"  card{n}.png 다시 그림 ({kb} KB)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"완료 — 카드 {len(changed)}장 고침")


if __name__ == "__main__":
    main()
