"""
표지 후보를 여러 장 만들어 독자들에게 고르게 하고, 이긴 것을 표지로 삼는다.

    python scripts/pick_cover.py cardiff-giant

표지는 이 계정에서 가장 많이 보이는 한 장이다. 피드에서도, 검색결과에서도,
프로필 격자에서도 보이는 게 표지다. 그런데 지금까지는 대본 쓰는 쪽이
혼자 정하고 아무도 확인하지 않았다. 카디프 자이언트에서 독자 다섯 명이
전원 "제일 센 사진을 2번에 묻어놨다"고 한 판이 있었다.

순서
  1. 후보 만들기 — 사진들을 보고 표지가 될 만한 구도 3개를 뽑는다
  2. 그려보기   — 실제 카드로 만든다. 말로 고르면 안 된다
  3. 투표       — 독자 다섯 명에게 어느 것이 스크롤을 멈추는지 묻는다
  4. 바꿔치기   — 이긴 것을 post.json 의 1번 카드로 넣고 다시 그린다

글(헤드라인·설명)은 그대로 두고 사진과 구도만 바꾼다. 그래야 무엇 때문에
이겼는지가 분명해진다.
"""

import base64
import json
import os
import shutil
import sys
import tempfile

import anthropic

import render_cards
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
sky from stone, and swipes.

Propose three genuinely different covers from the photographs supplied. Vary
the photograph, not just the crop — two crops of the same picture is one idea,
not two. Favour whichever photograph shows the actual subject most clearly,
even if another is prettier.

zoom must be 1.0 to 1.5. crop places the subject; remember the card is tall
and a wide photograph loses its left and right edges, so move the crop toward
the subject rather than leaving it at 50%.

Watch for scan artefacts — black mount edges, calibration strips, curator
handwriting on the negative. Half a word of handwriting left in a corner reads
as a mistake."""

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
                    "grade": {"type": "string",
                              "enum": ["base", "paper", "ink", "cold",
                                       "warm", "deep"]},
                    "why": {"type": "string"},
                },
                "required": ["image", "crop", "zoom", "grade", "why"],
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

If none of them would stop you, say so honestly by setting stops_scroll to
false and still naming the least bad one.

Write in KOREAN. Be specific about what your eye did."""

VOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "string", "enum": LETTERS},
        "why": {"type": "string"},
        "stops_scroll": {"type": "boolean"},
        "worst": {"type": "string", "enum": LETTERS},
    },
    "required": ["choice", "why", "stops_scroll", "worst"],
    "additionalProperties": False,
}


def photo_blocks(img_dir, images):
    blocks = []
    for img in images:
        path = os.path.join(img_dir, img["file"])
        ext = os.path.splitext(path)[1].lower()
        media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".png": "image/png"}.get(ext)
        if not media or not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        blocks.append({"type": "text", "text": f"Photograph: {img['file']}"})
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": media, "data": data}})
    return blocks


def png_block(path, label):
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return [{"type": "text", "text": label},
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/png",
                                         "data": data}}]


def propose(client, post, source, img_dir):
    """표지 후보 3개를 뽑는다."""
    blocks = photo_blocks(img_dir, source["images"])
    cover = post["cards"][0]
    prompt = f"""Subject: {source['subject']}

The cover headline is already written and will not change:
    "{cover['headline']}"
    {cover.get('note', '')}

Propose three covers for that headline using the photographs above."""

    r = client.messages.create(
        model=MODEL, max_tokens=3000, system=CANDIDATE_SYSTEM,
        output_config={"format": {"type": "json_schema",
                                  "schema": CANDIDATE_SCHEMA}},
        messages=[{"role": "user",
                   "content": blocks + [{"type": "text", "text": prompt}]}],
    )
    return json.loads(next(b.text for b in r.content if b.type == "text"))["covers"]


def vote(client, reader, blocks, headline):
    prompt = f"""You are {reader['name']}, {reader['age']}.

{reader['who']}

Above are {len(blocks) // 2} versions of the same cover. They all carry the
same words: "{headline}"

  choice        — 어느 것이 스크롤을 멈추는가
  why           — 왜 그런지. 눈이 어디로 갔는지 구체적으로.
  stops_scroll  — 고른 것이 정말 멈추게 하는가. 아니면 false.
  worst         — 제일 약한 것"""

    r = client.messages.create(
        model=MODEL, max_tokens=1500, system=VOTE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": VOTE_SCHEMA}},
        messages=[{"role": "user",
                   "content": blocks + [{"type": "text", "text": prompt}]}],
    )
    if r.stop_reason == "refusal":
        return None
    return json.loads(next(b.text for b in r.content if b.type == "text"))


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/pick_cover.py <슬러그>")
    slug = sys.argv[1]

    post_dir = os.path.join(ROOT, "posts", slug)
    with open(os.path.join(post_dir, "post.json"), encoding="utf-8") as f:
        post = json.load(f)
    with open(os.path.join(post_dir, "source.json"), encoding="utf-8") as f:
        source = json.load(f)

    img_dir = os.path.join(post_dir, post.get("image_dir", "img"))
    handle = post.get("handle", "@theglassnegative")
    client = anthropic.Anthropic()

    # ── 1. 후보 ──────────────────────────────────────────────────
    print("1단계 — 표지 후보 뽑기")
    known = {i["file"] for i in source["images"]}
    covers = []
    for c in propose(client, post, source, img_dir):
        if c["image"] not in known:
            print(f"  [무시] 없는 사진: {c['image']}")
            continue
        c["zoom"] = min(float(c["zoom"]), MAX_ZOOM)   # 표지는 확대하지 않는다
        covers.append(c)
    covers = covers[:len(LETTERS)]

    # 지금 쓰고 있는 표지도 후보에 넣는다. 새 후보가 더 나쁠 수도 있으니
    # 비교 대상이 있어야 한다.
    current = dict(post["cards"][0])
    covers.insert(0, {"image": current["image"], "crop": current["crop"],
                      "zoom": min(current.get("zoom", 1), MAX_ZOOM),
                      "grade": current.get("grade", "base"), "why": "지금 표지"})
    covers = covers[:len(LETTERS)]

    if len(covers) < 2:
        sys.exit("[중단] 비교할 후보가 부족합니다.")

    for letter, c in zip(LETTERS, covers):
        print(f"  {letter}: {c['image']} zoom {c['zoom']} {c['crop']} — {c['why'][:60]}")

    # ── 2. 그려보기 ──────────────────────────────────────────────
    print()
    print("2단계 — 후보를 실제 카드로 그리기")
    browser = render_cards.find_browser()
    tmp = tempfile.mkdtemp(dir=ROOT, prefix=".cover-")
    paths = []
    try:
        for letter, c in zip(LETTERS, covers):
            card = dict(post["cards"][0])
            card.update({"image": c["image"], "crop": c["crop"],
                         "zoom": c["zoom"], "grade": c["grade"]})
            out = os.path.join(tmp, f"cover-{letter}.png")
            kb = render_cards.shoot(
                render_cards.build_html(card, img_dir, handle, 1, len(post["cards"])),
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

        headline = post["cards"][0]["headline"]
        votes, tally = [], {letter: 0 for letter, _, _ in paths}
        for reader in READERS:
            try:
                said = vote(client, reader, blocks, headline)
            except Exception as e:
                print(f"  {reader['name']}: 실패 ({e})")
                continue
            if not said or said["choice"] not in tally:
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

        winner = max(tally, key=lambda k: tally[k])
        chosen = next(c for letter, c, _ in paths if letter == winner)
        stops = sum(1 for v in votes if v["stops_scroll"])

        # ── 4. 바꿔치기 ──────────────────────────────────────────
        print()
        print(f"4단계 — {winner} 로 표지 교체 "
              f"({tally[winner]}/{len(votes)}표)")

        post["cards"][0].update({
            "image": chosen["image"], "crop": chosen["crop"],
            "zoom": chosen["zoom"], "grade": chosen["grade"],
        })
        with open(os.path.join(post_dir, "post.json"), "w", encoding="utf-8") as f:
            json.dump(post, f, ensure_ascii=False, indent=2)

        kb = render_cards.shoot(
            render_cards.build_html(post["cards"][0], img_dir, handle,
                                    1, len(post["cards"])),
            os.path.join(post_dir, "card1.png"), browser, tmp)
        if kb < 60:
            sys.exit(f"[실패] 새 표지가 {kb} KB 뿐입니다.")

        with open(os.path.join(post_dir, "cover_vote.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"winner": winner, "tally": tally, "votes": votes,
                       "stops_scroll": stops, "asked": len(votes),
                       "chosen": chosen}, f, ensure_ascii=False, indent=2)

        print(f"  card1.png 다시 그림 ({kb} KB)")
        print(f"완료 — {len(votes)}명 중 {stops}명이 '이거면 멈춘다'고 함")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
