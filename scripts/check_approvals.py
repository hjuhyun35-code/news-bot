"""
텔레그램에서 누른 승인 단추를 읽어 실제로 발행한다.

    python scripts/check_approvals.py

30분마다 돈다. 새 승인이 없으면 아무것도 하지 않고 끝난다.

여기가 이 파이프라인에서 유일하게 바깥으로 나가는 자리라서
지키는 것이 세 가지 있다.

  1. 누가 눌렀는지 확인한다. 봇 주소는 누구나 찾을 수 있다.
  2. 단추가 보내온 글자를 그대로 믿지 않는다. 슬러그는 정해진 모양이어야
     하고 실제로 있는 폴더여야 한다.
  3. 처리 표시를 발행보다 먼저 한다. 중간에 죽으면 승인이 날아가는 쪽이
     같은 글이 두 번 올라가는 쪽보다 낫다. 승인은 다시 누르면 되지만
     두 번 올라간 글은 되돌릴 수 없다.
"""

import datetime
import json
import os
import re
import subprocess
import sys

import telegram

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def publish(slug):
    """발행 스크립트를 돌린다. 확인 문구는 사람이 단추를 눌렀을 때만 준다."""
    env = dict(os.environ)
    env["POST_SLUG"] = slug
    env["PUBLISH_CONFIRM"] = "PUBLISH"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "ig_publish.py")],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


# 처리가 끝난 뒤 보여줄 단추. 누르면 아무 일도 하지 않고 안내만 뜬다.
DONE = [[("✅ 올라감", "done")]]
DROPPED = [[("🗑 버림", "done")]]
RETRY = None   # 실패했을 때는 원래 단추를 그대로 둔다


def handle(cb):
    """단추 하나를 처리한다. (보여줄 글, 바꿀 단추)

    단추를 None 으로 돌려주면 원래 단추가 그대로 남는다. 실패했을 때
    그렇게 한다 — 고친 뒤 같은 자리에서 다시 누를 수 있어야 한다.
    """
    who = cb.get("from", {}).get("id")
    data = cb.get("data", "")

    if not telegram.is_owner(who):
        print(f"  [거절] 주인이 아닌 사람({who})이 눌렀습니다: {data}")
        return None, RETRY

    if data == "done":          # 이미 끝난 글의 단추를 다시 누른 것
        return None, RETRY

    if ":" not in data:
        return None, RETRY
    action, slug = data.split(":", 1)

    if not SLUG_OK.match(slug):
        print(f"  [거절] 이상한 슬러그: {slug!r}")
        return None, RETRY

    post_dir = os.path.join(ROOT, "posts", slug)
    if not os.path.exists(os.path.join(post_dir, "post.json")):
        return f"❌ {slug} — 대본 파일이 없습니다.", RETRY

    if os.path.exists(os.path.join(post_dir, "published.json")):
        return f"이미 올라간 글입니다: {slug}", DONE

    if action == "no":
        with open(os.path.join(post_dir, "rejected.json"), "w", encoding="utf-8") as f:
            json.dump({"rejected_at": now()}, f, ensure_ascii=False, indent=2)
        print(f"  {slug}: 버림")
        return f"🗑 버렸습니다: {slug}", DROPPED

    if action != "ok":
        return None, RETRY

    print(f"  {slug}: 발행 시작")
    ok, log = publish(slug)
    print(log)

    if not ok:
        # 단추를 그대로 남긴다. 원인을 고친 뒤 같은 자리에서 다시 누르면 된다.
        return f"❌ {slug} 발행 실패\n<pre>{log[-600:]}</pre>", RETRY

    with open(os.path.join(post_dir, "published.json"), "w", encoding="utf-8") as f:
        json.dump({"published_at": now()}, f, ensure_ascii=False, indent=2)
    return (f"✅ 올라갔습니다: {slug}\n"
            f"https://www.instagram.com/theglassnegative/"), DONE


def main():
    result, err = telegram.updates()
    if err:
        sys.exit(f"[실패] 텔레그램에서 답을 못 받았습니다: {err}")

    clicks = [u for u in result if "callback_query" in u]
    if not clicks:
        print("새 승인 없음")
        return

    # 먼저 전부 처리됨으로 표시한다. 아래에서 죽더라도 같은 승인이
    # 다음 실행에서 또 발행되는 일은 없어야 한다.
    telegram.updates(offset=max(u["update_id"] for u in result) + 1)
    print(f"승인 단추 {len(clicks)}개")

    for u in clicks:
        cb = u["callback_query"]
        if cb.get("data") == "done":
            telegram.answer(cb["id"], "이미 처리된 글입니다")
            continue

        telegram.answer(cb["id"], "처리 중…")
        buttons = RETRY
        try:
            text, buttons = handle(cb)
        except Exception as e:                # 하나가 터져도 나머지는 처리한다
            text = f"❌ 처리 중 오류: {e}"
            print(f"  [오류] {e}")

        if not text:
            continue
        msg = cb.get("message", {})
        if msg:
            telegram.edit(msg["chat"]["id"], msg["message_id"], text, buttons)
        else:
            telegram.say(text)


if __name__ == "__main__":
    main()
