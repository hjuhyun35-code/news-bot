"""오늘 이 실행이 무엇을 해야 하는지 정한다.

    python scripts/day_plan.py

깃허브 출력 형식으로 세 줄을 내놓는다.

    stop=yes|no    오늘 몫을 이미 채웠으면 yes. 그러면 아무것도 하지 않는다
    mode=publish|make
    slug=<슬러그>

하루에 여러 번 예약을 걸어두고, 실제로 몇 개를 올릴지는 여기서 정한다.
예약을 편수만큼만 걸면 깃허브가 건너뛸 때마다 그날 몫이 그대로 날아간다.
넉넉히 걸어두고 여기서 세는 편이 안전하다.

편수는 주마다 하나씩 늘어난다. 처음 2개, 4주째부터 5개에서 멈춘다.
계정이 갑자기 하루 다섯 개를 쏟아내면 사람이 보기에도 이상하고,
소재가 버티지 못한다.

mode=publish 는 만들어놓고 안 올린 초안이 있다는 뜻이다. 새로 만들지
않고 그것부터 올린다. 2026-08-04 에 wardenclyffe 가 이렇게 떠 있었다.
만드는 규칙이 "post.json 이 있으면 만든 것"이라 다시 걸리지도 않았다.
"""

import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS = os.path.join(ROOT, "posts")

KST = datetime.timezone(datetime.timedelta(hours=9))

# 이 날부터 센다. 예약 시각이 전부 한국 시간 기준이라 날짜도 한국 시간이다.
START = datetime.date(2026, 8, 6)

FIRST_WEEK = 2   # 첫 주 하루 편수
MOST = 5         # 여기서 멈춘다


def today():
    return datetime.datetime.now(KST).date()


def allowance(day):
    """그날 올려도 되는 편수."""
    if day < START:
        return 0
    weeks = (day - START).days // 7
    return min(FIRST_WEEK + weeks, MOST)


def published_on(day):
    """그날 이미 올라간 글 수. 표시 파일의 시각을 한국 시간으로 바꿔 센다."""
    count = 0
    if not os.path.isdir(POSTS):
        return 0
    for name in os.listdir(POSTS):
        path = os.path.join(POSTS, name, "published.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                when = json.load(f).get("published_at", "")
            if datetime.datetime.fromisoformat(when).astimezone(KST).date() == day:
                count += 1
        except (ValueError, OSError, json.JSONDecodeError):
            # 시각을 못 읽는 표시 파일은 오늘 것이 아니라고 본다. 세다가
            # 죽는 것보다 낫다 — 최악이라도 하루 한 개 더 올라갈 뿐이다.
            continue
    return count


def pending():
    """만들어놓고 올리지도 버리지도 않은 초안. 이름순.

    파일 시각으로 정렬하지 않는다. 깃허브에서 저장소를 새로 받으면 모든
    파일의 시각이 내려받은 시각이 되어 "오래된 것부터"가 뜻을 잃는다.
    이름순은 어디서 돌리든 같은 답을 준다.

    올라간 글에 published.json 이 반드시 있어야 이 판단이 맞는다.
    표시가 없으면 이미 올라간 글을 다시 올린다. 2026-08-05 에 tunguska 와
    voynich 가 그런 상태였고, 손으로 표시를 채워 넣었다.
    """
    out = []
    if not os.path.isdir(POSTS):
        return out
    for name in sorted(os.listdir(POSTS)):
        d = os.path.join(POSTS, name)
        if not os.path.exists(os.path.join(d, "post.json")):
            continue
        if os.path.exists(os.path.join(d, "published.json")):
            continue
        if os.path.exists(os.path.join(d, "rejected.json")):
            continue
        out.append(name)
    return out


def say(**kw):
    out = os.environ.get("GITHUB_OUTPUT")
    for key, value in kw.items():
        print(f"{key}={value}")
        if out:
            with open(out, "a", encoding="utf-8") as f:
                f.write(f"{key}={value}\n")


def main():
    day = today()
    allowed = allowance(day)
    done = published_on(day)
    print(f"오늘({day}) 몫 {allowed}개 중 {done}개 올렸습니다.", file=sys.stderr)

    # 손으로 돌릴 때 하나 더 만들고 싶은 경우가 있다. 예약 실행은 이 값을
    # 주지 않으니 저절로 몫을 지킨다.
    if os.environ.get("IGNORE_QUOTA") == "yes":
        print("몫을 무시하라고 했습니다.", file=sys.stderr)
        done, allowed = 0, max(allowed, 1)

    if done >= allowed:
        reason = "아직 시작 전입니다" if allowed == 0 else "오늘 몫을 채웠습니다"
        print(f"{reason}. 아무것도 하지 않습니다.", file=sys.stderr)
        say(stop="yes", mode="none", slug="")
        return

    waiting = pending()
    if waiting:
        print(f"밀린 초안 {len(waiting)}개: {', '.join(waiting)}", file=sys.stderr)
        say(stop="no", mode="publish", slug=waiting[0])
        return

    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "pick_subject.py")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # 소재가 떨어졌다. 실패로 남겨야 텔레그램 알림이 간다.
        sys.exit(r.stdout.strip() or r.stderr.strip() or "[중단] 소재를 고르지 못했습니다.")
    say(stop="no", mode="make", slug=r.stdout.strip())


if __name__ == "__main__":
    main()
