"""텔레그램에서 온 소식 하나를 처리한다.

    TELEGRAM_UPDATE='<업데이트 JSON>' python scripts/telegram_command.py

클라우드플레어 웹훅이 받은 것을 깃허브로 넘겨주면 이 스크립트가 받는다.
예약 실행을 기다리지 않으므로 누르는 즉시 처리된다.

웹훅과 getUpdates 는 같이 못 쓴다. 웹훅을 걸면 텔레그램은 소식을 그쪽으로만
보내고 getUpdates 는 409 를 돌려준다. 그래서 웹훅을 건 뒤에는 check_approvals
의 예약 실행이 아니라 이 경로가 실제로 일한다. check_approvals 는 웹훅이
걸려 있으면 스스로 물러난다.

할 줄 아는 것
  단추          ok:<슬러그> / no:<슬러그>  — check_approvals 의 판단을 그대로 쓴다
  "오늘꺼 초안"  초안 만들기를 시킨다. 다 되면 카드와 승인 단추가 온다
  "상태"        오늘 몇 개 올렸는지, 소재가 몇 개 남았는지

주인이 아닌 사람이 보낸 것은 조용히 버린다. 봇 주소는 누구나 찾을 수 있다.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import telegram
from check_approvals import handle, DONE, RETRY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("GITHUB_REPOSITORY", "hjuhyun35-code/news-bot")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

# 이 말들 중 하나가 글 안에 있으면 초안을 만든다. 사장님이 매번 똑같이
# 적을 리 없으니 넉넉하게 받는다.
DRAFT_WORDS = ["오늘꺼 초안", "오늘거 초안", "오늘 초안", "초안 만들", "초안만들"]
STATUS_WORDS = ["상태", "몇 개", "몇개", "남았"]


def github(path, payload):
    """깃허브 API 를 부른다. Actions 안에서 도니 토큰은 이미 있다."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "news-bot",
        },
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def start_draft():
    code, err = github("actions/workflows/daily.yml/dispatches",
                       {"ref": "main", "inputs": {"ignore_quota": "yes"}})
    if code >= 300:
        telegram.say(f"초안 만들기를 시작하지 못했습니다.\n<pre>{err}</pre>")
        sys.exit(f"[실패] 워크플로를 부르지 못했습니다: {code} {err}")
    telegram.say("초안을 만들기 시작했습니다. 7분쯤 걸립니다.\n"
                 "다 되면 카드와 함께 단추를 보내드립니다.")
    print("초안 만들기 시작함")


def report_status():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import day_plan

    day = day_plan.today()
    allowed = day_plan.allowance(day)
    done = day_plan.published_on(day)
    waiting = day_plan.pending()

    with open(os.path.join(ROOT, "queue.json"), encoding="utf-8") as f:
        subjects = json.load(f)["subjects"]
    left = sum(1 for s in subjects
               if not s.get("hold")
               and not os.path.exists(os.path.join(ROOT, "posts", s["slug"], "post.json")))

    lines = [f"<b>오늘 {done}/{allowed}개</b> 올렸습니다.",
             f"남은 소재 {left}개."]
    if waiting:
        lines.append(f"만들어놓고 안 올린 것: {', '.join(waiting)}")
    telegram.say("\n".join(lines))
    print("상태 보냄")


def on_text(msg):
    who = msg.get("from", {}).get("id")
    if not telegram.is_owner(who):
        print(f"  [무시] 주인이 아닌 사람({who})")
        return
    text = (msg.get("text") or "").strip()
    print(f"  글: {text!r}")

    if any(w in text for w in DRAFT_WORDS):
        start_draft()
    elif any(w in text for w in STATUS_WORDS):
        report_status()
    else:
        print("  아는 명령이 아닙니다. 아무것도 하지 않습니다.")


def on_button(cb):
    if cb.get("data") == "done":
        telegram.answer(cb["id"], "이미 처리된 글입니다")
        return
    telegram.answer(cb["id"], "처리 중…")
    buttons = RETRY
    try:
        text, buttons = handle(cb)
    except Exception as e:
        text = f"❌ 처리 중 오류: {e}"
        print(f"  [오류] {e}")
    if not text:
        return
    msg = cb.get("message", {})
    if msg:
        telegram.edit(msg["chat"]["id"], msg["message_id"], text, buttons)
    else:
        telegram.say(text)


def main():
    raw = os.environ.get("TELEGRAM_UPDATE", "").strip()
    if not raw:
        sys.exit("[실패] TELEGRAM_UPDATE 가 비어 있습니다.")
    try:
        update = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"[실패] 소식을 읽지 못했습니다: {e}")

    print(f"받은 소식: {', '.join(k for k in update if k != 'update_id')}")

    if "callback_query" in update:
        on_button(update["callback_query"])
    elif "message" in update:
        on_text(update["message"])
    else:
        print("처리할 것이 없습니다.")


if __name__ == "__main__":
    main()
