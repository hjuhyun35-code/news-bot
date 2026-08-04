"""
독자 셋의 반응과 사실 검증 결과를 보고, 올릴지 사람에게 물을지 정한다.

    python scripts/auto_publish.py cardiff-giant

사람 승인을 매번 받는 대신 독자 셋을 관문으로 쓴다. 통과하면 바로 올리고
텔레그램으로 알린다. 걸리면 올리지 않고 승인 단추를 보낸다.

막는 기준은 셋뿐이다. 많이 만들면 좋은 게시물까지 막힌다.

  1. 자료와 모순되는 주장이 있다  — 사실이 틀린 것. 되돌릴 수 없다
  2. 독자 전원이 그냥 넘긴다      — 올려도 아무도 안 본다
  3. 평균이 너무 낮다             — 계정 인상을 깎는다

"근거 없음"은 막지 않는다. 자료에 없다는 뜻이지 틀렸다는 뜻이 아니고,
막기 시작하면 거의 모든 게시물이 걸린다. 대신 알림에 적어 보낸다.

사진을 못 알아보겠다는 카드도 막지 않는다. 이미 자동으로 고쳐봤고,
못 고친 것은 알림에 적힌다. 사람이 보고 다음 소재에서 판단할 몫이다.
"""

import json
import os
import subprocess
import sys
import datetime

import telegram

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIN_SCORE = 4.0      # 평균이 이보다 낮으면 사람에게 넘긴다
MIN_READERS = 2      # 반응이 이보다 적으면 판단 근거가 부족하다


def load(post_dir, name, default=None):
    path = os.path.join(post_dir, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def judge(readers, check):
    """(올려도 되는가, 사람에게 넘기는 이유들)"""
    stop = []

    if not readers or readers.get("asked", 0) < MIN_READERS:
        stop.append("독자 반응을 충분히 못 받았습니다")
        return False, stop

    bad = [c for c in (check or {}).get("claims", [])
           if c["verdict"] == "contradicted"]
    for c in bad:
        stop.append(f"자료와 모순: {c['where']} — {c['claim'][:80]}")

    if readers["read_through"] == 0:
        stop.append(f"{readers['asked']}명 전원이 끝까지 안 봤습니다")

    if readers["average"] < MIN_SCORE:
        stop.append(f"독자 평균 {readers['average']}점 (기준 {MIN_SCORE}점)")

    return not stop, stop


def summary(slug, readers, check):
    lines = [f"<b>{slug}</b>"]
    if readers:
        lines.append(f"독자 {readers['average']}점 · "
                     f"{readers['asked']}명 중 {readers['read_through']}명 끝까지 봄")
        for r in readers["readers"]:
            lines.append(f"· {r['name']}({r['age']}) {r['score']}점 — {r['bad'][:90]}")

    weak = [c for c in (check or {}).get("claims", [])
            if c["verdict"] != "supported"]
    if weak:
        lines.append("")
        lines.append(f"⚠️ 자료로 확인 안 되는 주장 {len(weak)}개")
        for c in weak[:4]:
            lines.append(f"· {c['where']}: {c['claim'][:90]}")
    return lines


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/auto_publish.py <슬러그>")
    slug = sys.argv[1]

    post_dir = os.path.join(ROOT, "posts", slug)
    if load(post_dir, "published.json"):
        print("이미 올라간 글입니다. 아무것도 하지 않습니다.")
        return

    readers = load(post_dir, "readers.json")
    check = load(post_dir, "check.json")
    ok, stop = judge(readers, check)

    lines = summary(slug, readers, check)
    unfixed = load(post_dir, "unfixed.json")
    if unfixed:
        lines.append("")
        lines.append("⚠️ 사진을 못 알아보겠다는데 코드가 못 고친 카드")
        for c in unfixed["cards"]:
            lines.append(f"· {c}")

    if not ok:
        print("사람에게 넘깁니다:")
        for s in stop:
            print(f"  - {s}")
        telegram.say("\n".join(
            [f"🤔 <b>{slug}</b> — 올리지 않고 물어봅니다", ""]
            + [f"· {s}" for s in stop] + [""] + lines[1:]),
            buttons=[[("✅ 그래도 올리기", f"ok:{slug}"),
                      ("🗑 버리기", f"no:{slug}")]])
        return

    print("독자 관문 통과. 발행합니다.")
    env = dict(os.environ)
    env["POST_SLUG"] = slug
    env["PUBLISH_CONFIRM"] = "PUBLISH"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "ig_publish.py")],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    print(r.stdout[-2000:])
    print(r.stderr[-500:])

    if r.returncode != 0:
        telegram.say(f"❌ <b>{slug}</b> 발행 실패\n<pre>{r.stdout[-500:]}</pre>",
                     buttons=[[("🔁 다시 시도", f"ok:{slug}"),
                               ("🗑 버리기", f"no:{slug}")]])
        sys.exit("[실패] 발행에 실패했습니다.")

    media = ""
    for line in r.stdout.splitlines():
        if "게시물 번호" in line:
            media = line.split(":")[-1].strip()

    with open(os.path.join(post_dir, "published.json"), "w", encoding="utf-8") as f:
        json.dump({"published_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
            "media_id": media}, f, ensure_ascii=False, indent=2)

    telegram.say("\n".join(
        [f"✅ <b>{slug}</b> 올렸습니다",
         "https://www.instagram.com/theglassnegative/", ""] + lines[1:]))
    print(f"완료 — 게시물 {media}")


if __name__ == "__main__":
    main()
