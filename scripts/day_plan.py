"""오늘 이 실행이 무엇을 해야 하는지 정한다.

    python scripts/day_plan.py

깃허브 출력 형식으로 세 줄을 내놓는다.

    stop=yes|no    오늘 몫을 이미 채웠으면 yes. 그러면 아무것도 하지 않는다
    mode=publish|make
    slug=<슬러그>
    skipped=<건너뛴 슬러그들, 쉼표로>

make 일 때는 사진까지 확보해놓고 넘긴다. 사진이 모자란 소재를 만나면
queue.json 에 hold 를 적고 다음 소재로 넘어간다. 그런 소재는 흔하고,
2026-08-06 기준 넷 중 하나 꼴로 나온다. 예전에는 그때마다 실행이
실패로 끝나고 그날 몫이 통째로 날아갔다.

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

QUEUE = os.path.join(ROOT, "queue.json")
UNSUITABLE = 2   # find_images.py 가 "이 소재는 안 맞는다"고 답하는 코드
SKIP_LIMIT = 4   # 한 번에 이만큼까지만 건너뛴다. 그 이상이면 목록이 문제다
OUT_OF_SUBJECTS = 4   # 만들 소재가 없다는 뜻. 고장(1)과 구분한다


def hold_subject(slug, reason=""):
    """소재를 빼둔다. 사람이 손으로 하던 일이다.

    queue.json 을 통째로 다시 쓴다. 들여쓰기는 유지되지만 빈 줄은
    사라진다 — 파일이 기계와 사람 사이에 있으니 감수한다.
    """
    with open(QUEUE, encoding="utf-8") as f:
        data = json.load(f)
    for item in data["subjects"]:
        if item["slug"] == slug:
            item["hold"] = True
            item["why_hold"] = (
                f"{today()} 자동 확인. {reason or '사진 조건을 통과하지 못했다.'} "
                f"자세한 내용은 그날 실행 기록에 있다.")
            break
    with open(QUEUE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return reason or "사진 부족"


def today():
    return datetime.datetime.now(KST).date()


def allowance(day):
    """그날 올려도 되는 편수."""
    if day < START:
        return 0
    weeks = (day - START).days // 7
    return min(FIRST_WEEK + weeks, MOST)


# 그 소재가 끝났다는 표시. 둘 중 하나만 있으면 끝난 것이다.
#   published.json  인스타에 API 로 올렸다 (캐러셀 시절)
#   delivered.json  릴스 영상을 텔레그램으로 보냈다 (지금 방식)
# 릴스는 음원 때문에 사람이 앱에서 올린다. 그래서 우리 쪽 완료는
# "영상을 보냈다"까지다.
DONE_MARKS = (("published.json", "published_at"),
              ("delivered.json", "delivered_at"))


def finished_at(post_dir):
    """끝난 시각. 아직이면 None."""
    for name, key in DONE_MARKS:
        path = os.path.join(post_dir, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                when = json.load(f).get(key, "")
            return datetime.datetime.fromisoformat(when)
        except (ValueError, OSError, json.JSONDecodeError):
            # 시각을 못 읽어도 표시가 있으면 끝난 것이다. 세는 데만 못 쓴다.
            return False
    return None


def published_on(day):
    """그날 끝낸 수. 표시 파일의 시각을 한국 시간으로 바꿔 센다."""
    count = 0
    if not os.path.isdir(POSTS):
        return 0
    for name in os.listdir(POSTS):
        when = finished_at(os.path.join(POSTS, name))
        if when and when.astimezone(KST).date() == day:
            count += 1
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
        if finished_at(d) is not None:
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

    # 사람이 "새로 만들어줘"라고 부른 것이면 밀린 초안을 다시 내밀지
    # 않는다. 2026-08-09, 안 올린 초안 하나가 남아 있는 동안 초안을
    # 부를 때마다 같은 것만 계속 왔다. 예약 실행에는 맞는 규칙이지만
    # 사람이 직접 부를 때는 새것을 원한 것이다.
    waiting = [] if os.environ.get("NEW_SUBJECT") == "yes" else pending()
    if waiting:
        print(f"밀린 초안 {len(waiting)}개: {', '.join(waiting)}", file=sys.stderr)
        say(stop="no", mode="publish", slug=waiting[0])
        return

    # 사진까지 여기서 확보한다. 안 맞는 소재는 빼두고 다음 것을 집는다.
    skipped = []
    for _ in range(SKIP_LIMIT):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "pick_subject.py")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            # 소재가 떨어졌다. 고장이 아니라 재료가 없는 것이다.
            # 실패로 끝내면 재시도가 붙고, 다시 해도 소재는 안 생긴다.
            # 2026-08-26 에 목록이 바닥나 예약 실행마다 실패 알림이 갔다.
            print(r.stdout.strip() or r.stderr.strip()
                  or "[중단] 소재를 고르지 못했습니다.", file=sys.stderr)
            say(stop="yes", mode="none", slug="", empty="yes")
            sys.exit(OUT_OF_SUBJECTS)
        slug = r.stdout.strip()

        if os.path.exists(os.path.join(POSTS, slug, "source.json")):
            print(f"{slug}: 사진은 이미 있습니다", file=sys.stderr)
            say(stop="no", mode="make", slug=slug, skipped=",".join(skipped))
            return

        print(f"{slug}: 사진을 찾습니다", file=sys.stderr)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "find_images.py"), slug],
                           capture_output=True, text=True)
        # 사진 찾기가 무엇을 보고 판단했는지는 그대로 남긴다. 나중에
        # 목록을 손볼 때 이 기록 말고는 단서가 없다.
        print(r.stdout, file=sys.stderr)
        if r.stderr.strip():
            print(r.stderr, file=sys.stderr)

        if r.returncode == 0:
            say(stop="no", mode="make", slug=slug, skipped=",".join(skipped))
            return
        if r.returncode != UNSUITABLE:
            sys.exit(f"[중단] {slug} 사진 찾기가 고장났습니다 (종료 코드 {r.returncode}).")

        # 소재가 우리 기준에 안 맞는다. 흔한 일이다. 빼두고 다음으로 간다.
        told = [ln for ln in r.stdout.splitlines() if ln.startswith("[건너뜀]")]
        reason = told[-1].replace("[건너뜀]", "").strip() if told else ""
        reason = hold_subject(slug, reason)
        print(f"{slug}: 빼뒀습니다 — {reason}", file=sys.stderr)
        skipped.append(slug)

    sys.exit(f"[중단] 소재 {SKIP_LIMIT}개를 연달아 건너뛰었습니다: "
             f"{', '.join(skipped)}. 목록을 손봐야 합니다.")


if __name__ == "__main__":
    main()
