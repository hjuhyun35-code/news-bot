import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from nacl import encoding, public

REPO = os.environ["GITHUB_REPOSITORY"]
GH_PAT = os.environ.get("GH_SECRETS_PAT", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

TARGETS = [
    ("IG_ACCESS_TOKEN",
     "https://graph.instagram.com/refresh_access_token",
     "ig_refresh_token"),
    ("THREADS_ACCESS_TOKEN",
     "https://graph.threads.net/refresh_access_token",
     "th_refresh_token"),
]


def get_json(url, params=None, headers=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def gh(method, path, body=None):
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "news-bot-token-refresh",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def seal(public_key_b64, value):
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(value.encode())
    return base64.b64encode(sealed).decode()


def telegram(text):
    if not (TG_TOKEN and TG_CHAT):
        return
    try:
        data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data=data, method="POST")
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass


def main():
    if not GH_PAT:
        print("[실패] GH_SECRETS_PAT 이 없습니다. 금고에 등록했는지 확인하세요.")
        return 1

    try:
        key = gh("GET", f"/repos/{REPO}/actions/secrets/public-key")
    except urllib.error.HTTPError as e:
        print(f"[실패] 금고 접근 불가 (HTTP {e.code}).")
        print("       PAT 권한이 'Secrets: Read and write' 인지 확인하세요.")
        telegram(f"{REPO}: 토큰 갱신 실패 - GitHub PAT 문제 (HTTP {e.code})")
        return 1

    problems = []
    done = []

    for name, url, grant in TARGETS:
        current = os.environ.get(name, "").strip()
        if not current:
            print(f"{name}: 등록되어 있지 않음 - 건너뜀")
            continue

        try:
            res = get_json(url, {"grant_type": grant, "access_token": current})
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"{name}: 갱신 실패 (HTTP {e.code})")
            print(f"  {body[:300]}")
            problems.append(f"{name} 갱신 실패 (HTTP {e.code})")
            continue

        new_token = res.get("access_token")
        days = int(res.get("expires_in", 0)) // 86400
        if not new_token:
            print(f"{name}: 응답에 토큰이 없음")
            problems.append(f"{name} 응답 이상")
            continue

        try:
            gh("PUT", f"/repos/{REPO}/actions/secrets/{name}", {
                "encrypted_value": seal(key["key"], new_token),
                "key_id": key["key_id"],
            })
        except urllib.error.HTTPError as e:
            print(f"{name}: 금고 저장 실패 (HTTP {e.code})")
            problems.append(f"{name} 금고 저장 실패")
            continue

        print(f"{name}: 갱신 완료 - 앞으로 {days}일 유효 (길이 {len(new_token)})")
        done.append(f"{name} +{days}일")

    if problems:
        telegram(REPO + " 토큰 갱신 문제\n" + "\n".join(problems)
                 + "\n\n계속 실패하면 토큰을 새로 발급해야 합니다.")
        return 1

    if done:
        print()
        print("전부 정상입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
