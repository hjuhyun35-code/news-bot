"""
위키백과·위키미디어에서 받아오는 것들. 재시도가 붙어 있다.

여기 모아둔 이유: 위키미디어는 가끔 503(Backend fetch failed)을 낸다.
잠시 뒤 다시 부르면 대개 된다. 그런데 재시도가 없으면 아침 자동 실행이
그 한 번 때문에 통째로 실패하고, 그날은 게시물이 없다.

실제로 그렇게 하루를 날린 적이 있다 — 사진 24장을 다 고르고 내려받는
중에 한 장이 503을 냈다.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("GlassNegativeBot/1.0 "
      "(https://github.com/hjuhyun35-code/news-bot; hjuhyun35@gmail.com)")

# 다시 부르기까지 기다리는 시간(초).
#
# 2초, 6초 두 번이 전부였다. 503 한 번을 넘기기에는 충분했지만 429 는
# 그것보다 오래 간다. 2026-08-11 에 릴스 여섯 편을 연달아 만들다가 네
# 편이 여기서 죽었다 — 깃허브 서버는 IP 를 여럿이 나눠 쓰므로 위키미디어가
# 더 빨리 막는다. 1분까지 기다리면 대개 풀린다.
WAITS = [3, 10, 30, 60]

# 이 오류들은 잠시 뒤 다시 하면 대개 된다.
# 404 같은 것은 다시 해도 똑같으니 바로 포기한다.
RETRY_CODES = {429, 500, 502, 503, 504}

# 요청과 요청 사이에 이만큼은 쉰다.
#
# 2026-08-11, 429 를 맞고 103초를 기다려도 안 풀렸다. 짧은 제한이 아니라
# 지속적인 차단이었다. 같은 날 소재 50개를 검사할 때는 요청 사이에
# 0.4~0.7초를 쉬었고 76번을 물어도 한 번도 안 막혔다. 차이는 기다린
# 시간이 아니라 던진 속도였다.
#
# 한 소재에 스무 번 안팎을 부르므로 15초쯤 늘어난다. 7분짜리 작업에서
# 그 정도는 싸다 — 막히면 그날 몫이 통째로 날아간다.
MIN_GAP = 0.8
_last = 0.0


def _pace():
    """앞 요청과 너무 붙지 않게 한다."""
    global _last
    gap = time.monotonic() - _last
    if gap < MIN_GAP:
        time.sleep(MIN_GAP - gap)
    _last = time.monotonic()


def _open(url, timeout):
    last = None
    for attempt in range(len(WAITS) + 1):
        wait = WAITS[attempt] if attempt < len(WAITS) else None
        try:
            _pace()
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in RETRY_CODES:
                raise
            # 얼마나 기다리라고 알려주면 그 말을 따른다. 우리가 정한
            # 시간보다 길면 그쪽이 맞다.
            told = e.headers.get("Retry-After") if e.headers else None
            if told and wait is not None:
                try:
                    wait = max(wait, min(int(told), 120))
                except ValueError:
                    pass
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        if wait is None:
            break
        print(f"    (다시 시도 {attempt + 1}/{len(WAITS)} — {last}, {wait}초 뒤)")
        time.sleep(wait)
    raise last


def get_json(url, params=None, timeout=60):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return json.loads(_open(url, timeout).decode())


def fetch(url, timeout=120):
    """그림 같은 덩어리를 통째로 받아온다."""
    return _open(url, timeout)
