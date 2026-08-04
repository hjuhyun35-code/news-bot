"""
완성된 초안을 텔레그램으로 보내 승인을 받는다.

    python scripts/send_draft.py cardiff-giant

카드 6장, 캡션, 그리고 사실 검증에서 걸린 항목을 함께 보낸다.
걸린 항목은 접어놓지 않는다 — 승인 단추 바로 위에 그대로 보여준다.
문제가 있는 줄 알면서 누르는 것과 모르고 누르는 것은 다르다.

카드는 저장소 주소로 보낸다. 그래서 이 스크립트는 커밋과 푸시가
끝난 뒤에 돌아야 한다.
"""

import json
import os
import sys

import telegram

REPO = os.environ.get("GITHUB_REPOSITORY", "hjuhyun35-code/news-bot")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    # --cards-only 는 카드만 보내고 승인 단추는 안 붙인다. 자동 발행일 때
    # 쓴다 — 판단과 알림은 auto_publish 가 한다.
    cards_only = "--cards-only" in sys.argv
    if not args:
        sys.exit("사용법: python scripts/send_draft.py <슬러그> [--cards-only]")
    slug = args[0]

    post_dir = os.path.join(ROOT, "posts", slug)
    with open(os.path.join(post_dir, "post.json"), encoding="utf-8") as f:
        post = json.load(f)

    cards = post["cards"]
    urls = [f"{RAW}/posts/{slug}/{c['file']}" for c in cards]

    result, err = telegram.photos(urls, caption=f"{slug} — 카드 {len(cards)}장")
    if err:
        sys.exit(f"[실패] 카드를 보내지 못했습니다: {err}")
    print(f"카드 {len(cards)}장 보냄")
    if cards_only:
        return

    vote_path = os.path.join(post_dir, "cover_vote.json")
    if os.path.exists(vote_path):
        with open(vote_path, encoding="utf-8") as f:
            cv = json.load(f)
        lines = [f"<b>표지 투표</b> — {cv['winner']} 당선 "
                 f"({cv['tally'][cv['winner']]}/{cv['asked']}표)",
                 f"{cv['asked']}명 중 {cv['stops_scroll']}명이 "
                 f"'이거면 스크롤 멈춘다'고 했습니다."]
        if cv.get("adjusted"):
            lines.append(f"⚠️ {esc(cv['adjusted'])}")
        lines.append("")
        for v in cv["votes"]:
            lines.append(f"<b>{esc(v['name'])} ({v['age']})</b> → {v['choice']}"
                         f"{'' if v['stops_scroll'] else ' (그래도 안 멈춤)'}")
            lines.append(esc(v["why"]))
            lines.append("")
        telegram.say("\n".join(lines)[:4000])
        print(f"표지 투표 결과 보냄 ({cv['winner']} 당선)")

    # 독자 반응은 따로 보낸다. 승인 메시지에 합치면 길이 제한(4096자)에
    # 걸려서 정작 승인 단추가 잘려나간다.
    readers_path = os.path.join(post_dir, "readers.json")
    if os.path.exists(readers_path):
        with open(readers_path, encoding="utf-8") as f:
            rd = json.load(f)

        lines = [f"<b>독자 반응</b> — 평균 {rd['average']}점 / 10",
                 f"{rd['asked']}명 중 {rd['read_through']}명이 끝까지 봤습니다.",
                 ""]
        for r in rd["readers"]:
            lines.append(f"<b>{esc(r['name'])} ({r['age']})</b> "
                         f"{r['score']}점 · {esc(r['action'])}")
            lines.append(f"첫인상: {esc(r['first_second'])}")
            lines.append(f"👍 {esc(r['good'])}")
            lines.append(f"👎 {esc(r['bad'])}  (약한 카드 {r['weakest_card']}번)")
            if r.get("buried", "없음") not in ("없음", "", "None"):
                lines.append(f"📄 캡션에 묻힘: {esc(r['buried'])}")
            lines.append("")
        telegram.say("\n".join(lines)[:4000])
        print(f"독자 반응 보냄 (평균 {rd['average']}점)")

    # 사실 검증 결과
    problems = []
    check_path = os.path.join(post_dir, "check.json")
    if os.path.exists(check_path):
        with open(check_path, encoding="utf-8") as f:
            check = json.load(f)
        problems = [c for c in check["claims"] if c["verdict"] != "supported"]

    lines = [f"<b>{esc(slug)}</b>", ""]
    if os.path.exists(readers_path):
        lines.append(f"독자 {rd['average']}점 · "
                     f"{rd['asked']}명 중 {rd['read_through']}명 끝까지 봄")
    lines.append(f"캡션 {len(post['caption'])}자")
    lines.append("")
    lines.append(esc(post["caption"][:700]))
    if len(post["caption"]) > 700:
        lines.append("…")
    lines.append("")

    unfixed_path = os.path.join(post_dir, "unfixed.json")
    if os.path.exists(unfixed_path):
        with open(unfixed_path, encoding="utf-8") as f:
            uf = json.load(f)["cards"]
        lines.append("⚠️ <b>사진을 못 알아보겠다는데 코드가 못 고친 카드</b>")
        for c in uf:
            lines.append(f"· {esc(c)}")
        lines.append("이 사진은 바꾸는 편이 낫습니다.")
        lines.append("")

    if problems:
        lines.append(f"⚠️ <b>자료로 확인 안 되는 주장 {len(problems)}개</b>")
        for p in problems[:6]:
            mark = "모순" if p["verdict"] == "contradicted" else "근거없음"
            lines.append(f"· [{mark}] {esc(p['where'])}: {esc(p['claim'][:120])}")
        lines.append("")
        lines.append("올리기 전에 이 문장들을 고치거나 지우세요.")
    else:
        lines.append("✅ 모든 주장이 자료로 뒷받침됩니다.")

    _, err = telegram.say("\n".join(lines), buttons=[[
        ("✅ 승인하고 올리기", f"ok:{slug}"),
        ("✖️ 버리기", f"no:{slug}"),
    ]])
    if err:
        sys.exit(f"[실패] 승인 요청을 보내지 못했습니다: {err}")

    print(f"승인 요청 보냄 (확인 필요한 주장 {len(problems)}개)")


if __name__ == "__main__":
    main()
