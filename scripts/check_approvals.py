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

import base64
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

import telegram

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

REPO = os.environ.get("GITHUB_REPOSITORY", "hjuhyun35-code/news-bot")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def gh(method, path, payload=None):
    """깃허브 파일 API. (응답, 상태코드) 를 돌려준다."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {GH_TOKEN}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "User-Agent": "news-bot"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}"), r.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode()), e.code
        except Exception:
            return {}, e.code


def claim(slug):
    """발행하기 전에 자리를 잡는다. 잡았으면 파일의 sha, 못 잡았으면 None.

    깃허브에 파일을 '없을 때만 만들기'로 올린다. 이미 있으면 422 가 온다.
    이게 이 파이프라인에서 유일하게 원자적인 동작이다 — 두 실행이 동시에
    시도해도 하나만 성공한다.

    표시를 발행보다 먼저 남기는 이유는 이 파일 맨 위에 적힌 그대로다.
    승인이 날아가는 쪽이 같은 글이 두 번 올라가는 쪽보다 낫다. 2026-08-07
    에 nan-madol 이 12초 차이로 두 번 올라갔다 — 그때는 발행이 끝난 뒤에
    표시를 남기고 있었고, 뒤에 온 실행이 아직 빈 자리를 보고 또 올렸다.
    """
    body = json.dumps({"published_at": now(), "media_id": "",
                       "note": "발행 중입니다. 끝나면 게시물 번호가 채워집니다."},
                      ensure_ascii=False, indent=2) + "\n"
    res, code = gh("PUT", f"contents/posts/{slug}/published.json", {
        "message": f"발행 시작: {slug}",
        "content": base64.b64encode(body.encode()).decode(),
    })
    if code in (200, 201):
        return res.get("content", {}).get("sha")
    if code == 422:
        print(f"  다른 실행이 먼저 {slug} 를 가져갔습니다. 아무것도 하지 않습니다.")
        return None
    print(f"  [경고] 자리를 잡지 못했습니다 ({code}). 발행하지 않습니다: {res}")
    return None


def finish(slug, sha, media):
    body = json.dumps({"published_at": now(), "media_id": media},
                      ensure_ascii=False, indent=2) + "\n"
    gh("PUT", f"contents/posts/{slug}/published.json", {
        "message": f"published: {slug}",
        "content": base64.b64encode(body.encode()).decode(),
        "sha": sha,
    })


def give_back(slug, sha):
    """발행이 실패했으면 자리를 돌려놓는다. 그래야 다시 시도가 먹힌다."""
    gh("DELETE", f"contents/posts/{slug}/published.json",
       {"message": f"발행 실패로 표시를 되돌림: {slug}", "sha": sha})


def dispatch(workflow, inputs=None):
    """워크플로를 부른다. 단추 하나로 초안이나 릴스를 시작할 때 쓴다."""
    res, code = gh("POST", f"actions/workflows/{workflow}/dispatches",
                   {"ref": "main", "inputs": inputs or {}})
    if code >= 300:
        return False, json.dumps(res, ensure_ascii=False)[:200]
    return True, ""


def publish(slug):
    """발행 스크립트를 돌린다. 확인 문구는 사람이 단추를 눌렀을 때만 준다."""
    env = dict(os.environ)
    env["POST_SLUG"] = slug
    env["PUBLISH_CONFIRM"] = "PUBLISH"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "ig_publish.py")],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


# 처리가 끝난 뒤 보여줄 단추.
DROPPED = [[("🗑 버림", "done")]]
RETRY = None   # 실패했을 때는 원래 단추를 그대로 둔다


# 캐러셀과 릴스를 며칠 띄운다. 같은 사진이 프로필 격자에 나란히 걸리면
# 처음 온 사람에게 우려먹는 계정으로 보인다. 릴스는 안 팔로우한 사람에게
# 닿으므로, 그 사람이 프로필에 들어왔을 때 캐러셀이 아래에 따로 있는
# 편이 볼 것이 많은 계정으로 읽힌다.
REEL_GAP_DAYS = 4


def days_since_published(post_dir):
    """캐러셀을 올린 지 며칠 됐나. 아직 안 올렸으면 None."""
    path = os.path.join(post_dir, "published.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            when = json.load(f).get("published_at", "")
        then = datetime.datetime.fromisoformat(when)
        return (datetime.datetime.now(datetime.timezone.utc) - then).days
    except (ValueError, OSError, json.JSONDecodeError):
        return None


def done_buttons(slug):
    """올린 뒤에도 릴스 단추는 남긴다.

    릴스는 캐러셀과 며칠 띄워 올리는 편이 낫다. 프로필 격자에 같은
    사진이 나란히 걸리면 우려먹는 계정으로 보이기 때문이다. 그래서
    올리자마자가 아니라 나중에 누를 수 있어야 한다.
    """
    return [[("✅ 올라감", "done")], [("🎬 릴스 만들기", f"reel:{slug}")]]


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

    # 릴스는 올린 글이든 아직 안 올린 글이든 만들 수 있다. 그래서 발행
    # 여부를 보기 전에 처리한다. 원래 글은 손대지 않고 새 글로 답한다 —
    # 승인 메시지에 적힌 독자 반응과 검증 결과를 덮으면 안 된다.
    if action == "reel":
        started, err = dispatch("reel.yml", {"slug": slug})
        if not started:
            telegram.say(f"릴스 만들기를 시작하지 못했습니다: {slug}\n<pre>{err}</pre>")
            return None, RETRY

        print(f"  {slug}: 릴스 만들기 시작")
        note = ""
        days = days_since_published(post_dir)
        if days is not None and days < REEL_GAP_DAYS:
            # 막지는 않는다. 다만 오늘 캐러셀을 올렸다면 프로필 격자에
            # 같은 사진이 나란히 걸린다는 것은 알고 누르셔야 한다.
            note = (f"\n\n⚠️ 이 소재 캐러셀을 올린 지 "
                    f"{'오늘' if days == 0 else f'{days}일'}밖에 안 됐습니다. "
                    f"{REEL_GAP_DAYS}일쯤 띄우는 편이 낫습니다 — 프로필 격자에 "
                    f"같은 사진이 나란히 걸립니다. 영상은 만들어 보내드릴 테니 "
                    f"올리는 것만 미루셔도 됩니다.")
        telegram.say(f"🎬 <b>{slug}</b> 릴스를 만들고 있습니다. 5분쯤 걸립니다."
                     f"{note}")
        return None, RETRY

    if os.path.exists(os.path.join(post_dir, "published.json")):
        return f"이미 올라간 글입니다: {slug}", done_buttons(slug)

    if action == "no":
        with open(os.path.join(post_dir, "rejected.json"), "w", encoding="utf-8") as f:
            json.dump({"rejected_at": now()}, f, ensure_ascii=False, indent=2)
        print(f"  {slug}: 버림")
        return f"🗑 버렸습니다: {slug}", DROPPED

    if action != "ok":
        return None, RETRY

    # 자리부터 잡는다. 여기서 밀리면 다른 실행이 이미 올리고 있다는 뜻이다.
    # 내려받아둔 파일을 보는 것으로는 못 막는다 — 그 파일은 이 실행이
    # 시작할 때의 사진이라, 12초 뒤에 시작한 실행에게는 여전히 비어 있다.
    sha = claim(slug)
    if not sha:
        return f"이미 처리 중이거나 올라간 글입니다: {slug}", done_buttons(slug)

    print(f"  {slug}: 발행 시작")
    ok, log = publish(slug)
    print(log)

    if not ok:
        # 자리를 돌려놓아야 고친 뒤 같은 단추를 다시 누를 수 있다.
        give_back(slug, sha)
        return f"❌ {slug} 발행 실패\n<pre>{log[-600:]}</pre>", RETRY

    media = ""
    for line in log.splitlines():
        if "게시물 번호" in line:
            media = line.split(":")[-1].strip()
    finish(slug, sha, media)
    return (f"✅ 올라갔습니다: {slug}\n"
            f"https://www.instagram.com/theglassnegative/\n\n"
            f"릴스는 며칠 띄웠다가 만드세요. 프로필 격자에 같은 사진이 "
            f"나란히 걸리면 우려먹는 계정으로 보입니다."), done_buttons(slug)


def main():
    # 소식이 하나도 안 올 때 원인은 대개 둘 중 하나다. 웹훅이 걸려 있어서
    # 텔레그램이 그쪽으로 보내고 있거나, 다른 프로그램이 같은 봇을 함께
    # 폴링해서 먼저 가져가거나. 둘 다 여기서 드러난다.
    hook, err = telegram.call("getWebhookInfo", {})
    if err:
        print(f"봇 상태를 못 읽었습니다: {err}")
    elif hook:
        url = hook.get("url") or "(없음)"
        print(f"웹훅: {url} · 대기 중인 소식 {hook.get('pending_update_count', 0)}건")
        if hook.get("url"):
            # 웹훅이 걸려 있으면 텔레그램은 그쪽으로만 보낸다. 여기서
            # getUpdates 를 부르면 409 를 받는다. 물러나는 것이 맞다 —
            # 실제 처리는 telegram_command.py 가 즉시 하고 있다.
            print("웹훅이 걸려 있습니다. 이 예약 실행은 할 일이 없습니다.")
            return

    me, err = telegram.call("getMe", {})
    if me:
        print(f"봇: @{me.get('username')} (번호 {me.get('id')})")

    result, err = telegram.updates()
    if err:
        sys.exit(f"[실패] 텔레그램에서 답을 못 받았습니다: {err}")

    # 무엇이 왔는지 항상 남긴다. "새 승인 없음" 만 찍히면 단추를 눌렀는데
    # 안 왔는지, 아예 안 눌렀는지 구분할 수 없다.
    kinds = {}
    for u in result:
        for key in u:
            if key != "update_id":
                kinds[key] = kinds.get(key, 0) + 1
    print(f"받은 소식 {len(result)}건: {kinds or '(없음)'}")

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
