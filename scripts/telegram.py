"""
텔레그램에 말을 걸고 답을 받아오는 공용 함수들.

승인 단추가 이 파이프라인의 유일한 사람 관문이다. 그래서 여기서
지켜야 할 것이 하나 있다 — **누가 눌렀는지 반드시 확인한다.**
봇 주소는 누구나 찾을 수 있고, 확인하지 않으면 모르는 사람이 누른
단추로 인스타에 글이 올라간다.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"


def call(method, params):
    """텔레그램 API 한 번 호출. 실패해도 예외를 던지지 않는다."""
    if not TOKEN:
        return None, "TELEGRAM_BOT_TOKEN 이 비어 있습니다."
    data = urllib.parse.urlencode(params).encode()
    try:
        req = urllib.request.Request(f"{API}/{method}", data=data)
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read().decode())
        if not body.get("ok"):
            return None, body.get("description", "알 수 없는 오류")
        return body["result"], None
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        return None, f"HTTP {e.code} {detail}"
    except Exception as e:
        return None, str(e)


def say(text, buttons=None):
    """글 한 줄 보내기. buttons 는 [[(보이는 글, 눌렀을 때 값)]] 모양."""
    params = {"chat_id": CHAT, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "true"}
    if buttons:
        params["reply_markup"] = json.dumps({"inline_keyboard": [
            [{"text": label, "callback_data": value} for label, value in row]
            for row in buttons
        ]})
    return call("sendMessage", params)


def photos(urls, caption=""):
    """사진 여러 장을 한 묶음으로. 저장소가 공개라 주소만 주면 된다."""
    media = [{"type": "photo", "media": u} for u in urls[:10]]
    if caption:
        media[0]["caption"] = caption[:1000]
    return call("sendMediaGroup", {"chat_id": CHAT, "media": json.dumps(media)})


def video(path, caption=""):
    """영상 파일을 올려 보낸다. 주소가 아니라 파일 자체를 보낸다.

    카드 사진은 저장소가 공개라 주소만 줘도 됐지만, 영상은 저장소에
    넣지 않는다. 하나에 15~25MB라 몇 달이면 저장소가 감당 못 한다.
    그래서 만든 자리에서 곧바로 올린다.

    봇이 보낼 수 있는 파일은 50MB 까지다. 릴스 하나가 그보다 크면
    카드 수를 줄이거나 화질을 낮춰야 한다.
    """
    if not TOKEN:
        return None, "TELEGRAM_BOT_TOKEN 이 비어 있습니다."

    size = os.path.getsize(path)
    if size > 50 * 1024 * 1024:
        return None, f"{size / 1e6:.0f}MB 라 텔레그램 한도(50MB)를 넘습니다."

    boundary = "----newsbot" + os.urandom(8).hex()
    fields = {"chat_id": CHAT, "caption": caption[:1000],
              "supports_streaming": "true"}

    body = bytearray()
    for key, val in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        body += f"{val}\r\n".encode()
    body += f"--{boundary}\r\n".encode()
    body += (f'Content-Disposition: form-data; name="video"; '
             f'filename="{os.path.basename(path)}"\r\n').encode()
    body += b"Content-Type: video/mp4\r\n\r\n"
    with open(path, "rb") as f:
        body += f.read()
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{API}/sendVideo", data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            answer = json.loads(r.read().decode())
        if not answer.get("ok"):
            return None, answer.get("description", "알 수 없는 오류")
        return answer["result"], None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} {e.read().decode()[:300]}"
    except Exception as e:
        return None, str(e)


def updates(offset=None):
    """안 읽은 답들. offset 을 주면 그 앞의 것들은 읽은 걸로 처리된다.

    어디까지 읽었는지는 텔레그램 쪽이 기억한다. 우리가 파일로 들고 있지
    않는 이유다 — 들고 있으면 실행이 중간에 죽었을 때 어긋난다.
    """
    params = {"timeout": "0"}
    if offset is not None:
        params["offset"] = str(offset)
    return call("getUpdates", params)


def answer(callback_id, text=""):
    """단추 누른 사람 화면의 로딩 표시를 멈춘다."""
    return call("answerCallbackQuery",
                {"callback_query_id": callback_id, "text": text})


def keyboard(buttons):
    return json.dumps({"inline_keyboard": [
        [{"text": label, "callback_data": value} for label, value in row]
        for row in buttons
    ]})


def edit(chat_id, message_id, text, buttons=None):
    """이미 보낸 글을 고친다.

    buttons 를 주지 않으면 단추가 아예 사라진다. 그러면 눌렸는지 아닌지
    화면에 안 남고, 실패했을 때 다시 누를 수도 없다. 그래서 처리가 끝나면
    상태를 보여주는 단추로 바꾸고, 실패했을 때는 원래 단추를 그대로 둔다.
    """
    params = {"chat_id": chat_id, "message_id": message_id,
              "text": text, "parse_mode": "HTML"}
    if buttons:
        params["reply_markup"] = keyboard(buttons)
    return call("editMessageText", params)


def is_owner(user_id):
    """이 사람이 계정 주인인가. 여기가 뚫리면 아무나 발행할 수 있다."""
    return CHAT and str(user_id) == CHAT
