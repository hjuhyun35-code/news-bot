"""만든 릴스 영상을 텔레그램으로 보낸다.

    python scripts/send_reel.py greek-fire

깃허브 첨부파일은 컴퓨터에서 받아 휴대폰으로 옮겨야 한다. 텔레그램으로
보내면 휴대폰에서 바로 저장해 인스타 앱으로 넘어갈 수 있다.

캡션도 같이 보낸다. 인스타 앱에서 올릴 때 붙여넣을 것이기 때문이다.
"""

import glob
import json
import os
import sys

import telegram

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/send_reel.py <슬러그>")
    slug = sys.argv[1]

    post_dir = os.path.join(ROOT, "posts", slug)
    reels = sorted(glob.glob(os.path.join(post_dir, "reel*.mp4")))
    if not reels:
        sys.exit(f"[실패] {slug} 에 영상이 없습니다.")

    for path in reels:
        name = os.path.basename(path)
        size = os.path.getsize(path) / 1_000_000
        _, err = telegram.video(path, f"{slug} — {name} ({size:.1f}MB)")
        if err:
            print(f"  {name}: 못 보냈습니다 — {err}")
            telegram.say(f"릴스 영상을 보내지 못했습니다: {name}\n{err}")
            continue
        print(f"  {name}: 보냄 ({size:.1f}MB)")

    # 캡션은 따로 보낸다. 영상 설명에 붙이면 길이 제한에 잘린다.
    post_json = os.path.join(post_dir, "post.json")
    if os.path.exists(post_json):
        with open(post_json, encoding="utf-8") as f:
            caption = json.load(f).get("caption", "")
        if caption:
            telegram.say("아래는 인스타에 붙여넣을 캡션입니다. "
                         "영상을 저장한 뒤 앱에서 올리시고 음원을 고르세요.")
            telegram.say(caption[:4000])
            print("  캡션 보냄")


if __name__ == "__main__":
    main()
