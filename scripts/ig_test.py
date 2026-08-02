"""
인스타 연결 시험 — 실제로 게시하지는 않는다.

하는 일:
  1) 토큰이 어느 계정 것인지 확인
  2) 카드 1장으로 '게시물 컨테이너'를 만들어 본다
  3) 만들어지면 게시 권한이 살아 있다는 뜻

컨테이너를 만드는 것까지가 instagram_business_content_publish 권한을 쓰는 지점이라,
여기까지 성공하면 실제 게시도 된다. 발행(media_publish)은 호출하지 않으므로
계정에는 아무것도 올라가지 않는다.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://graph.instagram.com/v23.0"

REPO = os.environ.get("GITHUB_REPOSITORY", "hjuhyun35-code/news-bot")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
TEST_IMAGE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/posts/tunguska/card1.png"


def call(method, path, params):
    url = f"{API}/{path}"
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        url = f"{url}?{data.decode()}"
        req = urllib.request.Request(url, method="GET")
    else:
        req = urllib.request.Request(url, data=data, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return None, json.loads(body)
        except json.JSONDecodeError:
            return None, {"raw": body, "status": e.code}


def main():
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        print("[실패] IG_ACCESS_TOKEN 이 비어 있습니다.")
        print("       GitHub 저장소 Settings > Secrets and variables > Actions 에")
        print("       IG_ACCESS_TOKEN 이 등록되어 있는지, 이름 철자가 맞는지 확인하세요.")
        return 1

    print("=" * 60)
    print("1단계 — 토큰이 어느 계정 것인지 확인")
    print("=" * 60)

    me, err = call("GET", "me", {"fields": "id,username", "access_token": token})
    if err:
        print("[실패] 토큰이 인스타에서 거부되었습니다.")
        print(json.dumps(err, ensure_ascii=False, indent=2))
        print()
        print("흔한 원인:")
        print("  - 토큰을 복사할 때 앞뒤 공백이 섞였다")
        print("  - 토큰이 만료되었다 (60일)")
        return 1

    print(f"  계정: @{me.get('username')}")
    print(f"  번호: {me.get('id')}")
    if me.get("username") != "theglassnegative":
        print()
        print(f"  [경고] 예상과 다른 계정입니다. 개인 계정으로 연결되었을 수 있습니다.")
        print(f"         이대로 진행하면 그 계정에 글이 올라갑니다.")
        return 1
    print("  → 맞습니다.")
    print()

    print("=" * 60)
    print("2단계 — 게시물 컨테이너 만들기 (발행 아님)")
    print("=" * 60)
    print(f"  사진: {TEST_IMAGE}")

    created, err = call("POST", "me/media", {
        "image_url": TEST_IMAGE,
        "caption": "connection test — not published",
        "access_token": token,
    })

    if err:
        e = err.get("error", err)
        msg = e.get("message", "")
        print()
        print("[실패] 컨테이너를 만들지 못했습니다.")
        print(json.dumps(err, ensure_ascii=False, indent=2))
        print()

        if "permission" in msg.lower() or e.get("code") in (200, 10, 803):
            print(">>> 게시 권한(instagram_business_content_publish)이 없습니다.")
            print(">>> 앱 설정에서 권한을 추가하고 계정을 다시 연결해야 합니다.")
        elif "media" in msg.lower() or "url" in msg.lower() or "fetch" in msg.lower():
            print(">>> 인스타가 사진을 가져오지 못했습니다.")
            print(">>> 저장소가 Public 인지, 사진 경로가 맞는지 확인하세요.")
            print(f">>> 이 주소를 브라우저에 넣어 사진이 보이면 경로는 맞습니다:")
            print(f">>> {TEST_IMAGE}")
        return 1

    cid = created.get("id")
    print(f"  컨테이너 번호: {cid}")
    print()
    print("=" * 60)
    print("성공 — 게시 권한이 살아 있습니다.")
    print("계정에는 아무것도 올라가지 않았습니다.")
    print("(만들어진 컨테이너는 발행하지 않으면 하루 뒤 자동으로 사라집니다)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
