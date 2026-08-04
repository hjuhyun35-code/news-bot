"""
대본을 쓰기 전에, 표지에 쓸 사진을 독자 투표로 먼저 정한다.

    python scripts/pick_cover.py cardiff-giant

표지는 이 계정에서 가장 많이 보이는 한 장이다. 피드에서도, 검색결과에서도,
프로필 격자에서도 보이는 게 표지다.

**이 단계는 반드시 write_post.py 보다 먼저 돈다.** 대본을 먼저 쓰면 제일 좋은
사진이 이미 본문 어딘가에 들어가버리고, 표지는 남은 것 중에서만 고를 수
있다. 카디프 자이언트에서 실제로 그렇게 됐다 — 독자 다섯 명이 전원 "제일
센 사진(석판화)을 왜 표지로 안 썼냐"고 했는데, 그건 이미 2번 카드가
쓰고 있었다.

순서
  1. 후보 만들기 — 사진들을 보고 표지가 될 구도 3개와 임시 문구를 뽑는다
  2. 그려보기   — 실제 카드로 만든다. 말로 고르면 안 된다
  3. 투표       — 독자 다섯 명에게 어느 것이 스크롤을 멈추는지 묻는다
  4. 기록       — 이긴 것을 source.json 에 적는다. 대본 쪽이 이걸 따른다

여기서 정한 문구는 임시다. 진짜 헤드라인은 대본 쪽이 자료를 보고 쓴다.
여기서 재는 것은 글이 아니라 사진의 힘이다.
"""

import base64
import json
import os
import shutil
import sys
import tempfile

import anthropic

import render_cards
from llm import answer_of, image_block
from reader_reactions import READERS

MODEL = "claude-opus-5"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LETTERS = ["A", "B", "C", "D"]
MAX_ZOOM = 1.5


CANDIDATE_SYSTEM = """You design the cover card of an Instagram carousel for an
account about unexplained history told with public domain archive photographs.

The cover is the only card most people ever see. It is met at thumbnail size,
while scrolling fast, by someone who has never heard of this account. It has
one job: make them stop.

What stops a scroll is a photograph where the subject is instantly readable —
you can tell what it is before you read a word. A crop so tight that the
picture becomes texture does the opposite: the reader cannot tell ground from
sky from stone, and swipes. A drawing or a print that shows the subject
clearly beats a photograph of the real thing that is too dark or too damaged
to read.

Propose three genuinely different covers from the photographs supplied. Vary
the photograph, not just the crop — two crops of one picture is one idea, not
two. Favour whichever photograph shows the actual subject most clearly, even
if another is prettier or more authentic.

fit "crop" fills the card and cuts the sides off. fit "whole" shows the entire
photograph inside the card with a blurred copy of itself filling the space
above and below. Use "whole" when the subject spans a wide photograph and
cropping would leave only a piece of it — a body lying down, a row of people,
a long building. A reader cannot recognise a torso; they can recognise a whole
figure. Do not use "whole" on a stereocard or any picture wider than about
1.7:1 — it becomes a thin strip and the mount board shows.

At least one of your three candidates must use "whole" if any supplied
photograph is wider than it is tall and shows its subject end to end.

zoom must be 1.0 to 1.5, and is ignored when fit is "whole". crop places the
subject; the card is tall, so a wide photograph loses its left and right edges
— move the crop toward the subject rather than leaving it at 50%.

Watch for scan artefacts — black mount edges, grey calibration strips, curator
handwriting. Half a word of handwriting left in a corner reads as a mistake.

Also write a provisional hook for each: under 10 words, the kind of line this
account opens with. It is a placeholder so the card can be judged as a card;
the real headline gets written later."""

CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "covers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image": {"type": "string"},
                    "crop": {"type": "string"},
                    "zoom": {"type": "number"},
                    "fit": {"type": "string", "enum": ["crop", "whole"]},
                    "grade": {"type": "string",
                              "enum": ["base", "paper", "ink", "cold",
                                       "warm", "deep"]},
                    "hook": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["image", "crop", "zoom", "fit", "grade",
                             "hook", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["covers"],
    "additionalProperties": False,
}

VOTE_SYSTEM = """You are a real person scrolling Instagram, not a reviewer.

You are shown the same post's cover done several different ways. Pick the one
that would actually stop your thumb. Not the one that is most tasteful, most
historically interesting, or most effortful — the one that stops you.

Judge the photograph, not the wording. The words on these cards are
placeholders and will be rewritten; what is being decided is which picture
earns the stop.

If none of them would stop you, say so honestly by setting stops_scroll to
false and still naming the least bad one. That answer is genuinely useful —
it means the cover has to be built differently, and saying it costs nothing.

Write in KOREAN. Be specific about what your eye did."""

VOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "string", "enum": LETTERS},
        "why": {"type": "string"},
        "stops_scroll": {"type": "boolean"},
        "unreadable": {"type": "array",
                       "items": {"type": "string", "enum": LETTERS}},
        "worst": {"type": "string", "enum": LETTERS},
    },
    "required": ["choice", "why", "stops_scroll", "unreadable", "worst"],
    "additionalProperties": False,
}


def photo_blocks(img_dir, images):
    blocks = []
    for img in images:
        block = image_block(os.path.join(img_dir, img["file"]))
        if not block:
            continue
        blocks.append({"type": "text", "text": f"Photograph: {img['file']}"})
        blocks.append(block)
    return blocks


def png_block(path, label):
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return [{"type": "text", "text": label},
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/png",
                                         "data": data}}]


def propose(client, source, img_dir):
    blocks = photo_blocks(img_dir, source["images"])
    prompt = (f"Subject: {source['subject']}\n\n"
              f"Propose three covers for a post about this, using the "
              f"photographs above.")

    r = client.messages.create(
        model=MODEL, max_tokens=8000, system=CANDIDATE_SYSTEM,
        output_config={"format": {"type": "json_schema",
                                  "schema": CANDIDATE_SCHEMA}},
        messages=[{"role": "user",
                   "content": blocks + [{"type": "text", "text": prompt}]}],
    )
    return answer_of(r, "표지 후보")["covers"]


def vote(client, reader, blocks):
    prompt = f"""You are {reader['name']}, {reader['age']}.

{reader['who']}

Above are {len(blocks) // 2} versions of the same post's cover.

  choice        — 어느 것이 스크롤을 멈추는가
  why           — 왜 그런지. 눈이 어디로 갔는지 구체적으로.
  stops_scroll  — 고른 것이 정말 멈추게 하는가. 아니면 false.
  unreadable    — 사진이 뭘 찍은 건지 알아볼 수 없는 것을 전부. 없으면 빈 목록.
  worst         — 제일 약한 것"""

    r = client.messages.create(
        model=MODEL, max_tokens=4000, system=VOTE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": VOTE_SCHEMA}},
        messages=[{"role": "user",
                   "content": blocks + [{"type": "text", "text": prompt}]}],
    )
    return answer_of(r, "표지 투표")


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/pick_cover.py <슬러그>")
    slug = sys.argv[1]

    post_dir = os.path.join(ROOT, "posts", slug)
    src_path = os.path.join(post_dir, "source.json")
    with open(src_path, encoding="utf-8") as f:
        source = json.load(f)

    img_dir = os.path.join(post_dir, "img")
    handle = source.get("handle", "@theglassnegative")
    client = anthropic.Anthropic()

    # ── 1. 후보 ──────────────────────────────────────────────────
    print("1단계 — 표지 후보 뽑기")
    known = {i["file"] for i in source["images"]}
    covers = []
    for c in propose(client, source, img_dir):
        if c["image"] not in known:
            print(f"  [무시] 없는 사진: {c['image']}")
            continue
        c["zoom"] = min(float(c["zoom"]), MAX_ZOOM)   # 표지는 확대하지 않는다
        covers.append(c)
    covers = covers[:len(LETTERS)]

    if len(covers) < 2:
        sys.exit("[중단] 비교할 후보가 부족합니다.")

    for letter, c in zip(LETTERS, covers):
        print(f"  {letter}: {c['image']} zoom {c['zoom']} {c['crop']} "
              f"— {c['hook']}")

    # ── 2. 그려보기 ──────────────────────────────────────────────
    print()
    print("2단계 — 후보를 실제 카드로 그리기")
    browser = render_cards.find_browser()
    tmp = tempfile.mkdtemp(dir=ROOT, prefix=".cover-")
    try:
        paths = []
        for letter, c in zip(LETTERS, covers):
            card = {"layout": "cover", "image": c["image"], "crop": c["crop"],
                    "zoom": c["zoom"], "fit": c.get("fit", "crop"),
                    "grade": c["grade"], "headline": c["hook"], "source": ""}
            out = os.path.join(tmp, f"cover-{letter}.png")
            kb = render_cards.shoot(
                render_cards.build_html(card, img_dir, handle, 1, 6),
                out, browser, tmp)
            if kb < 60:
                print(f"  {letter}: 그리기 실패 ({kb} KB) — 후보에서 뺍니다")
                continue
            paths.append((letter, c, out))
            print(f"  {letter}: {kb} KB")

        if len(paths) < 2:
            sys.exit("[중단] 그려진 후보가 부족합니다.")

        # ── 3. 투표 ──────────────────────────────────────────────
        print()
        print("3단계 — 독자 투표")
        blocks = []
        for letter, _, out in paths:
            blocks += png_block(out, f"표지 {letter}")

        votes, tally = [], {letter: 0 for letter, _, _ in paths}
        for reader in READERS:
            try:
                said = vote(client, reader, blocks)
            except Exception as e:
                print(f"  {reader['name']}: 실패 ({e})")
                continue
            if said["choice"] not in tally:
                continue
            said["name"] = reader["name"]
            said["age"] = reader["age"]
            votes.append(said)
            tally[said["choice"]] += 1
            mark = "" if said["stops_scroll"] else "  (그래도 안 멈춤)"
            print(f"  {reader['name']}({reader['age']}) → {said['choice']}{mark}"
                  f"  {said['why'][:60]}")

        if not votes:
            sys.exit("[중단] 투표를 받지 못했습니다.")

        # 여러 사람이 못 알아보는 후보는 표를 받았어도 표지가 될 수 없다.
        # 나란히 놓고 고를 때는 "그중 나은 것"을 고르게 되지만, 피드에서는
        # 비교 대상 없이 혼자 지나간다.
        blind = {}
        for v in votes:
            for letter in v.get("unreadable", []):
                blind[letter] = blind.get(letter, 0) + 1
        dead = {l for l, c in blind.items() if c >= 3}
        for letter in sorted(dead):
            print(f"  [실격] {letter}: {blind[letter]}명이 못 알아봄")

        alive = {l: v for l, v in tally.items() if l not in dead} or tally
        winner = max(alive, key=lambda k: alive[k])
        chosen = next(c for letter, c, _ in paths if letter == winner)
        stops = sum(1 for v in votes if v["stops_scroll"])

        # ── 4. 기록 ──────────────────────────────────────────────
        print()
        print(f"4단계 — {winner} 를 표지로 ({tally[winner]}/{len(votes)}표)")

        source["cover"] = {"image": chosen["image"], "crop": chosen["crop"],
                           "zoom": chosen["zoom"], "fit": chosen.get("fit", "crop"),
                           "grade": chosen["grade"]}
        with open(src_path, "w", encoding="utf-8") as f:
            json.dump(source, f, ensure_ascii=False, indent=2)

        with open(os.path.join(post_dir, "cover_vote.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"winner": winner, "tally": tally, "votes": votes,
                       "stops_scroll": stops, "asked": len(votes),
                       "chosen": chosen}, f, ensure_ascii=False, indent=2)

        print(f"  source.json 에 표지 지정: {chosen['image']}")
        print(f"완료 — {len(votes)}명 중 {stops}명이 '이거면 멈춘다'고 함")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
