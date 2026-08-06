import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://graph.instagram.com/v23.0"

REPO = os.environ.get("GITHUB_REPOSITORY", "hjuhyun35-code/news-bot")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
SLUG = os.environ.get("POST_SLUG", "tunguska").strip()
CONFIRM = os.environ.get("PUBLISH_CONFIRM", "").strip()

# 묶음이 준비됐다고 해놓고 발행은 아직 못 받을 때 인스타가 주는 값
NOT_READY_YET = 2207027
PUBLISH_TRIES = 6
PUBLISH_WAIT = 15   # 초


def call(method, path, params):
    url = f"{API}/{path}"
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}", method="GET")
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return None, json.loads(body)
        except json.JSONDecodeError:
            return None, {"raw": body, "status": e.code}


def fail(msg, err=None):
    print()
    print(f"[실패] {msg}")
    if err:
        print(json.dumps(err, ensure_ascii=False, indent=2))
    sys.exit(1)


def wait_ready(container_id, label, tries=30, delay=4):
    for i in range(tries):
        res, err = call("GET", container_id,
                        {"fields": "status_code,status", "access_token": TOKEN})
        if err:
            fail(f"{label} 상태를 확인하지 못했습니다.", err)
        code = res.get("status_code")
        if code == "FINISHED":
            return True
        if code == "ERROR":
            fail(f"{label} 처리 중 인스타에서 오류가 났습니다.", res)
        print(f"    {label} 준비 중... ({code}, {i * delay}초)")
        time.sleep(delay)
    fail(f"{label} 가 제한 시간 안에 준비되지 않았습니다.")


def main():
    if not TOKEN:
        fail("IG_ACCESS_TOKEN 이 비어 있습니다.")

    post_path = os.path.join("posts", SLUG, "post.json")
    if not os.path.exists(post_path):
        fail(f"{post_path} 파일이 없습니다.")

    with open(post_path, encoding="utf-8") as f:
        post = json.load(f)

    cards = post["cards"]
    caption = post["caption"]

    print("=" * 60)
    print(f"게시물: {SLUG}   카드 {len(cards)}장")
    print("=" * 60)

    me, err = call("GET", "me", {"fields": "id,username", "access_token": TOKEN})
    if err:
        fail("토큰이 거부되었습니다.", err)
    if me.get("username") != "theglassnegative":
        fail(f"연결된 계정이 @{me.get('username')} 입니다. 예상과 다릅니다.")
    print(f"계정 확인: @{me['username']}")
    print()

    print("1단계 — 카드별 컨테이너 만들기")
    children = []
    for i, card in enumerate(cards, 1):
        image_url = f"{RAW}/posts/{SLUG}/{card['file']}"
        params = {
            "image_url": image_url,
            "is_carousel_item": "true",
            "access_token": TOKEN,
        }
        if card.get("alt"):
            params["alt_text"] = card["alt"]

        res, err = call("POST", "me/media", params)

        if err and "alt_text" in params:
            print(f"  카드 {i}: 대체텍스트가 거부되어 없이 재시도합니다")
            params.pop("alt_text")
            res, err = call("POST", "me/media", params)

        if err:
            fail(f"카드 {i} ({card['file']}) 컨테이너를 만들지 못했습니다.", err)

        cid = res["id"]
        children.append(cid)
        print(f"  카드 {i}: {cid}")

    print()
    print("2단계 — 카드들이 준비될 때까지 대기")
    for i, cid in enumerate(children, 1):
        wait_ready(cid, f"카드 {i}")
    print("  전부 준비됨")
    print()

    print("3단계 — 6장을 하나로 묶기")
    parent, err = call("POST", "me/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(children),
        "caption": caption,
        "access_token": TOKEN,
    })
    if err:
        fail("묶음 컨테이너를 만들지 못했습니다.", err)

    parent_id = parent["id"]
    print(f"  묶음 번호: {parent_id}")
    wait_ready(parent_id, "묶음")
    print()

    if CONFIRM != "PUBLISH":
        print("=" * 60)
        print("여기까지 전부 성공했습니다. 발행은 하지 않았습니다.")
        print("확인칸에 PUBLISH 를 입력하면 실제로 올라갑니다.")
        print("=" * 60)
        return

    print("4단계 — 발행")

    # 묶음이 FINISHED 라고 답한 뒤에도 인스타가 아직 발행을 못 받는
    # 때가 있다 — 2026-08-06 codex-gigas 가 여기서 죽었다.
    #
    #   code 9007 / subcode 2207027
    #   "The media is not ready for publishing, please wait for a moment"
    #
    # 준비 상태를 다시 물어봐야 소용없다. 이미 FINISHED 라고 답한다.
    # 그냥 조금 기다렸다가 다시 요청하면 된다. 이 오류만 다시 시도한다 —
    # 다른 오류에서 다시 부르면 같은 글이 두 번 올라갈 수 있다.
    published = None
    for attempt in range(1, PUBLISH_TRIES + 1):
        published, err = call("POST", "me/media_publish", {
            "creation_id": parent_id,
            "access_token": TOKEN,
        })
        if not err:
            break
        detail = (err or {}).get("error", {})
        if detail.get("error_subcode") != NOT_READY_YET:
            fail("발행에 실패했습니다.", err)
        if attempt == PUBLISH_TRIES:
            fail(f"묶음이 {PUBLISH_TRIES}번 시도까지 발행 준비가 안 됐습니다.", err)
        print(f"    아직 준비 중이랍니다. {PUBLISH_WAIT}초 뒤 다시 "
              f"({attempt}/{PUBLISH_TRIES})")
        time.sleep(PUBLISH_WAIT)

    print()
    print("=" * 60)
    print(f"올라갔습니다.  게시물 번호: {published.get('id')}")
    print("https://www.instagram.com/theglassnegative/")
    print("=" * 60)


if __name__ == "__main__":
    main()
