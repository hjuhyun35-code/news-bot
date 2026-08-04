"""
소재 하나를 받아 카드 대본(post.json)을 만든다.

    python scripts/write_post.py voynich

posts/<slug>/source.json 을 읽어 시작한다. 그 파일에는 주제 이름, 위키백과
문서 제목, 쓸 사진 목록만 들어 있으면 된다. 나머지는 이 스크립트가 채운다.

순서
  1. 자료 수집  — 위키백과 본문 + 사진마다 위키미디어 기록
  2. 안전 검사  — 범죄/실종/음모론이면 여기서 중단
  3. 작가       — 모은 자료만 보고 대본 작성
  4. 검사관     — 대본의 주장을 자료와 하나씩 대조
  5. 저장       — post.json + check.json

작가와 검사관은 별도 호출이다. 같은 대화에서 "네가 쓴 걸 검토해봐"라고 하면
자기 글을 변호하기 때문에 검사가 무의미해진다.
"""

import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import anthropic

MODEL = "claude-opus-5"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "GlassNegativeBot/1.0 (hjuhyun35@gmail.com)"

# 이 주제들은 아예 만들지 않는다. 사람이 관련된 사건은 유족이 있고,
# 음모론은 계정을 조용히 죽인다.
BANNED = [
    "murder", "killer", "homicide", "serial killer", "massacre",
    "missing person", "disappearance of", "abduction", "kidnap",
    "suicide", "lynching", "torture", "execution of",
    "conspiracy", "hoax theory", "cover-up", "false flag",
    "ufo sighting", "alien abduction", "paranormal", "haunted",
]


def get(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def wikipedia_extract(title):
    """위키백과 본문을 평문으로. 이게 작가가 볼 유일한 이야기 자료다."""
    data = get("https://en.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "prop": "extracts",
        "explaintext": "1", "redirects": "1", "titles": title,
    })
    pages = data["query"]["pages"]
    page = next(iter(pages.values()))
    if "extract" not in page:
        sys.exit(f"[실패] 위키백과에서 '{title}' 문서를 찾지 못했습니다.")
    return page["extract"]


def commons_record(commons_title):
    """사진 한 장의 공식 기록. 설명·날짜·저작자·라이선스."""
    data = get("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "prop": "imageinfo",
        "iiprop": "extmetadata|url|size", "titles": commons_title,
    })
    pages = data["query"]["pages"]
    page = next(iter(pages.values()))
    if "imageinfo" not in page:
        sys.exit(f"[실패] 위키미디어에서 '{commons_title}' 를 찾지 못했습니다.")

    meta = page["imageinfo"][0].get("extmetadata", {})

    def field(name):
        raw = meta.get(name, {}).get("value", "")
        return re.sub(r"<[^>]+>", " ", raw).strip()

    return {
        "title": page["title"],
        "description": field("ImageDescription"),
        "date": field("DateTimeOriginal"),
        "author": field("Artist"),
        "license": field("LicenseShortName"),
        "width": page["imageinfo"][0].get("width"),
        "height": page["imageinfo"][0].get("height"),
    }


WRITER_SYSTEM = """You write short Instagram carousels for @theglassnegative,
an account about unexplained history told with public domain archive photographs.

THE ONE RULE: every factual claim you write must be supported by the source
material provided in this message. You have general knowledge about the world.
Do not use it. If the sources do not say something, you cannot claim it. This is
not a stylistic preference — an unsupported claim is a defect that gets the post
rejected.

When you are tempted to add a detail that "must be true" or that you remember
from elsewhere, that is exactly the failure this rule exists to prevent.

Card structure:
  1  cover    — the hook. A question or a flat contradiction. Under 10 words.

     THE COVER MUST SHOW THE THING. A reader meets this card at thumbnail size
     while scrolling fast, and they have to be able to tell what they are
     looking at without reading a word. Show the whole subject, in frame,
     recognisable. Use zoom 1 to 1.4 — a tight crop turns a photograph into an
     unreadable patch of texture, and a reader who cannot tell whether they are
     looking at ground, sky, or stone swipes past. Save the detail crops for
     the body cards, where the headline has already told them what it is.

     body     — one fact per card, and the strongest facts you have.
     closing  — the answer first. Then what is still genuinely open.

WHAT GOES ON A CARD, AND WHAT GOES IN THE CAPTION

Before you write anything, find the things in the sources that a reader would
repeat to somebody else that evening. Those go on the cards, one per card.
The caption is for what would not fit.

The most common way this account produces a dull post is by spending its best
material in the caption. The caption takes a tap to open. Most people do not
tap. A fact that appears only in the caption did not appear.

The closing card must pay off the cover. If the cover asked a question, the
closing card answers it in its headline — plainly, in words, not by
implication. Only after answering does it name what is still unknown. A
closing card that just asks another question wastes the reader's last swipe
and leaves them with nothing.

If the sources say the thing was a hoax, a fake, a mistake, or was solved,
that belongs on a card. Not in the caption. On a card.

Voice: plain, declarative, specific. Short sentences. No hype words
("mind-blowing", "you won't believe", "shocking"). Never overclaim mystery —
if the sources say a thing is explained, say it is explained and make the
surprising part the hook instead. Being accurate is the entire point of this
account.

Wrap 2-5 words per headline in <y></y> to highlight them in yellow.

You can SEE each photograph — they are attached. Use that. Pick the crop by
looking at where the subject actually sits in the frame, not by guessing.

For each card also choose:
  image  — filename from the supplied list
  crop   — CSS object-position, e.g. "52% 46%". The card is 1080x1350 (tall).
           A wide photo will be cropped left and right, so a subject near an
           edge WILL be cut off unless you move the crop toward it. Look at the
           photograph and place the crop on the subject.
  zoom   — 1 for full frame, 2-3 for a detail crop. Zoom in when the interesting
           part is small in the frame, or to avoid scan borders and blank margins.

           Zoom is a spice, not a default. ONE card in the post may go past 2.
           An old photograph pushed to 2.5 stops being a photograph of a thing
           and becomes a patch of grey; readers cannot tell stone from soil
           from sky, and a card whose picture says nothing is a wasted card.
           Before zooming past 2, name the thing you are zooming into — a
           face, a hand, a joint, a line of print. If you cannot name it,
           do not zoom.

           Library scans often photograph the physical object, not just the
           picture: a black mount board, a grey-scale calibration strip along
           one edge, curator pencil marks. None of that may appear on a card.
           Zoom past it.

           A stereocard shows the SAME view twice, side by side. Never use it
           whole — the card would look like a printing error, and the vertical
           seam between the halves must not appear on the card.

           Do not reach for the obvious crop here. The card is much taller
           than a stereocard is, so the frame has already thrown away most of
           the left and right before your crop value applies — "35%" does not
           land where you would expect, it lands close to the seam. Use
           zoom 3 or more with crop "20% 50%" for the left half or
           "80% 50%" for the right half. Push it further out, not less.

           If you use both halves, put them on cards far apart in the set.

           If two of your images are the front and back of one object, crop
           them to completely different things — the picture on one, a block
           of the printed text on the other.

  fit    — "crop" fills the card and cuts the sides off. That is the default
           and it is right most of the time.

           "whole" shows the entire photograph inside the card, with a blurred
           copy of itself filling the space above and below. Use it when the
           subject is spread across a wide photograph and cropping would leave
           only a piece of it — a body lying down, a row of people, a long
           building, a wide landscape with the thing at one end. A reader
           cannot recognise a torso; they can recognise a whole figure.
           zoom and crop are ignored when you choose "whole".

  note   — under 150 characters. Two short sentences. Six lines of text on a
           card is a wall, and readers swipe past walls.

  grade  — base (dark photographs), paper (documents, drawings, anything on
           paper or vellum), ink (close-ups of handwriting or print),
           cold (wide empty landscapes), warm (fire, heat, explosion),
           deep (the closing card)

The bottom ~340px of a body card is covered by a black caption bar, and the
bottom ~25% of a cover/closing card is darkened for text. Do not put the
subject there.

ONE PHOTOGRAPH PER CARD. Every card uses a different photograph, and every
supplied photograph is used exactly once. Never put the same picture on two
cards — a reader who swipes onto a picture they just saw thinks the swipe
did not register, and swipes away. Vary the crops and grades too.

The `source` line is a human credit line printed small along the bottom edge.
Write it the way a museum caption would, NOT as a filename. Under 60 characters
so it fits on one line. Name the photographer or expedition when the record
gives one, otherwise describe the item.
  good:  "Wardenclyffe, 1904 · public domain"
  good:  "American Press Association, 1917 · public domain"
  good:  "Tesla, US patent 1,119,732 · public domain"
  bad:   "File:Wardenclyffe Tower - 1904.jpg, unknown author, public domain"

In the caption, credit the images the same way — a short readable sentence,
never a list of filenames."""

CHECKER_SYSTEM = """You verify factual claims against source material. You are
deliberately separate from whoever wrote the claims — do not defend them.

For each claim, decide:
  supported   — the sources state this, or it follows directly from them
  unsupported — plausible, but the sources do not say it
  contradicted — the sources say otherwise

"Unsupported" is not an accusation of falsehood. A claim can be true in the
world and still be unsupported here. That distinction is the whole job: the
account's credibility depends on only publishing what the record shows.

The photographs themselves are sources, and they are attached. If a claim is
about what is visible in an image — a structure, a posture, damage, or text
printed or written on the object — read the image and judge it on that. When
you can read the words yourself, quote them and mark it supported. Do not mark
something unsupported merely because the written records fail to repeat what
the photograph plainly shows.

Quote the exact supporting sentence when you mark something supported. If you
cannot find a quote, it is not supported."""


def image_blocks(post_dir, images):
    """사진을 실제로 보여준다. 안 보고 크롭을 고르면 피사체가 잘린다."""
    blocks = []
    for img in images:
        path = os.path.join(post_dir, "img", img["file"])
        ext = os.path.splitext(path)[1].lower()
        media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".png": "image/png", ".webp": "image/webp"}.get(ext)
        if not media or not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        blocks.append({"type": "text", "text": f"Photograph: {img['file']}"})
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": media, "data": data}})
    return blocks


def call(client, system, prompt, schema, extra_blocks=None):
    content = list(extra_blocks or []) + [{"type": "text", "text": prompt}]
    r = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    )
    if r.stop_reason == "refusal":
        sys.exit("[중단] 모델이 이 주제를 거부했습니다. 소재를 바꾸세요.")
    text = next(b.text for b in r.content if b.type == "text")
    return json.loads(text)


CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "caption": {"type": "string"},
        "cards": {
            # 개수 제한은 여기 못 쓴다. 구조화 출력은 minItems 가 0이나 1일
            # 때만 받아준다. 개수는 tidy() 가 센다.
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "layout": {"type": "string", "enum": ["cover", "body", "closing"]},
                    "image": {"type": "string"},
                    "crop": {"type": "string"},
                    "zoom": {"type": "number"},
                    "fit": {"type": "string", "enum": ["crop", "whole"]},
                    "grade": {"type": "string",
                              "enum": ["base", "paper", "ink", "cold", "warm", "deep"]},
                    "stamp": {"type": "string"},
                    "headline": {"type": "string"},
                    "note": {"type": "string"},
                    "source": {"type": "string"},
                    "alt": {"type": "string"},
                },
                "required": ["layout", "image", "crop", "zoom", "fit", "grade",
                             "headline", "source", "alt"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["caption", "cards"],
    "additionalProperties": False,
}

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "where": {"type": "string"},
                    "verdict": {"type": "string",
                                "enum": ["supported", "unsupported", "contradicted"]},
                    "quote": {"type": "string"},
                },
                "required": ["claim", "where", "verdict", "quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

SAFETY_SCHEMA = {
    "type": "object",
    "properties": {
        "safe": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["safe", "reason"],
    "additionalProperties": False,
}


CAPTION_MAX = 2200   # 인스타 캡션 한도
ALT_MAX = 100
SOURCE_MAX = 70
MIN_CARDS = 4        # 이보다 적으면 게시물이 안 된다
MAX_CARDS = 6        # 이보다 많으면 끝까지 보는 사람이 없다
COVER_ZOOM_MAX = 1.5 # 표지는 확대하면 안 된다. 아래 tidy() 주석 참고
NOTE_MAX = 150       # 설명글. 길면 카드가 글 벽이 된다
DETAIL_ZOOM = 2.0    # 이보다 세게 확대한 카드는 한 장만 남긴다


def card_count(images):
    """카드 수는 사진 수가 정한다. 사진 한 장에 카드 한 장.

    전에는 카드를 항상 6장 만들었다. 사진이 4장뿐인 소재에서는 두 장이
    반복됐고, 독자 다섯 명이 매번 "같은 사진이 또 나왔다, 스와이프가
    안 먹은 줄 알았다"고 했다. 크롭을 다르게 하는 걸로는 안 된다 —
    같은 사진은 같은 사진으로 보인다. 사진 다섯 장짜리 다섯 카드가
    사진 넷을 늘린 여섯 카드보다 낫다.
    """
    return max(MIN_CARDS, min(MAX_CARDS, len(images)))


def tidy(post, known_images):
    """길이와 형식은 부탁이 아니라 검사로 지킨다.

    프롬프트에 '60자 이하로' 라고 써도 모델은 자주 넘긴다. 고칠 수 있는 건
    여기서 고치고, 못 고치는 건 실패로 만들어 사람이 보게 한다.
    """
    fixed, problems = [], []

    # 개수와 구조부터. 한 번은 카드 1장짜리 대본이 끝까지 통과한 적이 있다.
    cards = post["cards"]
    want_n = card_count(known_images)
    if len(cards) != want_n:
        problems.append(f"카드가 {len(cards)}장 (있어야 할 수 {want_n}장)")
    else:
        want = ["cover"] + ["body"] * (want_n - 2) + ["closing"]
        got = [c.get("layout") for c in cards]
        if got != want:
            problems.append(f"카드 구성이 잘못됨: {' / '.join(got)}")

    # 사진 한 장에 카드 한 장. 같은 사진이 두 번 나오면 스와이프가 안 먹은
    # 것처럼 보인다. 붙어 있든 떨어져 있든 마찬가지다.
    used = [c.get("image") for c in cards]
    for img in sorted({i for i in used if used.count(i) > 1}):
        where = [str(n) for n, i in enumerate(used, 1) if i == img]
        problems.append(f"{img} 이 {', '.join(where)}번 카드에 겹쳐 쓰임")

    # 표지를 확대하면 사진이 알아볼 수 없는 얼룩이 된다. 독자 다섯 명 중
    # 넷이 "표지가 뭘 찍은 건지 모르겠다"고 한 판이 실제로 있었다.
    if cards and cards[0].get("zoom", 1) > COVER_ZOOM_MAX:
        problems.append(f"표지 확대가 {cards[0]['zoom']}배 "
                        f"(한도 {COVER_ZOOM_MAX}배). 표지는 피사체 전체가 보여야 합니다")

    # 확대는 양념이어야 한다. 오래된 기록사진을 두세 배로 당기면 형체가
    # 사라지고 얼룩만 남는다. 제일 세게 당긴 한 장만 남기고 나머지는 푼다.
    # 확대를 푸는 쪽은 사진이 더 많이 보이는 쪽이라 안전한 자동 수정이다.
    deep = [(n, c) for n, c in enumerate(cards[1:], 2)
            if c.get("zoom", 1) > DETAIL_ZOOM]
    for n, card in sorted(deep, key=lambda x: -x[1]["zoom"])[1:]:
        was = card["zoom"]
        card["zoom"] = DETAIL_ZOOM
        fixed.append(f"카드 {n} 확대를 {was}배에서 {DETAIL_ZOOM}배로 품")

    for n, card in enumerate(cards, 1):
        # 설명글이 길면 문장 단위로 뒤에서 덜어낸다. 문장 중간을 자르면
        # 말이 끊기지만, 문장을 통째로 빼면 짧아질 뿐이다.
        note = card.get("note", "")
        if len(note) > NOTE_MAX:
            parts = re.split(r"(?<=[.!?])\s+", note)
            kept = ""
            for part in parts:
                if kept and len(kept) + 1 + len(part) > NOTE_MAX:
                    break
                kept = f"{kept} {part}".strip()
            if kept and kept != note:
                card["note"] = kept
                fixed.append(f"카드 {n} 설명을 {len(note)}자에서 {len(kept)}자로 줄임")

        if card.get("image") not in known_images:
            problems.append(f"카드 {n} 이 없는 사진을 가리킴: {card.get('image')}")

        src = card.get("source", "")
        # "File:Wardenclyffe Tower - 1904.jpg, ..." 같은 파일명 접두어 제거
        cleaned = re.sub(
            r"^\s*File:.*?\.(jpg|jpeg|png|gif|tif|tiff|pdf)\s*[,.;–—-]*\s*",
            "", src, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;–—-")
        if cleaned and cleaned != src:
            card["source"] = cleaned
            fixed.append(f"카드 {n} 출처에서 파일명 제거 → \"{cleaned}\"")
        if len(card["source"]) > SOURCE_MAX:
            problems.append(f"카드 {n} 출처가 {len(card['source'])}자 (한도 {SOURCE_MAX})")
        # 대체텍스트는 사진 설명이라 뒤를 잘라도 틀린 말이 되지 않는다.
        # 여덟 자 넘겼다고 실행 전체를 죽이면 그날 게시물이 없다.
        # 캡션과 출처는 자르지 않는다 — 캡션은 끝에 출처와 해시태그가 있고,
        # 출처는 자르면 "public domain" 이 떨어져 나간다.
        alt = card.get("alt", "")
        if len(alt) > ALT_MAX:
            cut = alt[:ALT_MAX].rsplit(" ", 1)[0].rstrip(" ,.;-") or alt[:ALT_MAX]
            card["alt"] = cut
            fixed.append(f"카드 {n} 대체텍스트를 {len(alt)}자에서 {len(cut)}자로 줄임")
    if len(post["caption"]) > CAPTION_MAX:
        problems.append(f"캡션이 {len(post['caption'])}자 (한도 {CAPTION_MAX})")
    return fixed, problems


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/write_post.py <슬러그>")
    slug = sys.argv[1]

    post_dir = os.path.join(ROOT, "posts", slug)
    src_path = os.path.join(post_dir, "source.json")
    if not os.path.exists(src_path):
        sys.exit(f"[실패] {src_path} 가 없습니다.")

    with open(src_path, encoding="utf-8") as f:
        src = json.load(f)

    client = anthropic.Anthropic()

    # ── 1. 자료 수집 ─────────────────────────────────────────────
    print(f"소재: {src['subject']}")
    print("1단계 — 자료 모으기")

    article = wikipedia_extract(src["wikipedia"])
    print(f"  위키백과 본문 {len(article):,}자")

    images = []
    for img in src["images"]:
        rec = commons_record(img["commons"])
        rec["file"] = img["file"]
        images.append(rec)
        print(f"  {img['file']}: {rec['date'] or '날짜 미상'} · {rec['license']}")
        if "public domain" not in rec["license"].lower():
            sys.exit(f"[중단] {img['file']} 이 저작권 만료가 아닙니다: {rec['license']}")

    # ── 2. 안전 검사 ─────────────────────────────────────────────
    print()
    print("2단계 — 금지 주제 검사")

    lowered = (src["subject"] + " " + article[:4000]).lower()
    hits = [w for w in BANNED if w in lowered]
    if hits:
        print(f"  키워드 걸림: {', '.join(hits)}")

    verdict = call(client, "You screen subjects for a history account.", f"""
Subject: {src['subject']}

Opening of the source article:
{article[:3000]}

This account does NOT publish:
- unsolved murders, missing persons, or any case with identifiable victims
- anything where surviving relatives could plausibly be alive and hurt by it
- conspiracy theories, or subjects whose audience is mainly conspiracy-minded
- UFO / paranormal claims presented as open questions

Keyword scan flagged: {hits or 'nothing'}. Keywords are noisy — a keyword hit
in an unrelated context is fine, and a clean scan does not mean the subject is
safe. Judge the subject itself.

Is this subject safe to publish?""".strip(), SAFETY_SCHEMA)

    if not verdict["safe"]:
        sys.exit(f"[중단] 이 소재는 만들지 않습니다.\n       사유: {verdict['reason']}")
    print(f"  통과 — {verdict['reason']}")

    # ── 3. 작가 ──────────────────────────────────────────────────
    print()
    print("3단계 — 대본 작성")

    records = "\n\n".join(
        f"FILE: {i['file']}\n"
        f"Archive title: {i['title']}\n"
        f"Description: {i['description'] or '(none recorded)'}\n"
        f"Date: {i['date'] or '(none recorded)'}\n"
        f"Author: {i['author'] or '(none recorded)'}\n"
        f"Licence: {i['license']}"
        for i in images
    )

    # 카드 수는 사진 수가 정한다. 사진을 늘려 쓰지 않는다.
    n_cards = card_count({i["file"] for i in src["images"]})
    print(f"  사진 {len(src['images'])}장 → 카드 {n_cards}장")

    # 표지는 이미 독자 투표로 정해졌다. 대본은 그 위에 글만 얹는다.
    cover = src.get("cover")
    cover_rule = ""
    if cover:
        cover_rule = (
            f"\nCARD 1 IS ALREADY DECIDED. Readers were shown several covers "
            f"and chose this one:\n"
            f"  image {cover['image']}, crop \"{cover['crop']}\", "
            f"zoom {cover['zoom']}, grade {cover['grade']}\n"
            f"Use exactly those four values for card 1 and write its headline "
            f"to suit that picture. Do NOT use {cover['image']} on card 2 — "
            f"swiping from the cover onto the same photograph reads as a "
            f"swipe that did not register.\n")

    post = call(client, WRITER_SYSTEM, f"""
Subject: {src['subject']}

=== SOURCE ARTICLE (the only story material you may use) ===
{article[:60000]}

=== PHOTOGRAPH RECORDS (the only thing you may say about the images) ===
{records}

Write exactly {n_cards} cards and the caption — one card per photograph.

The caption opens with the question people actually type into a search engine
about this subject, then tells the story in short paragraphs, then states plainly
what is still unresolved, then credits the images, then 3-5 hashtags.

The caption may repeat what the cards say — most readers never open it, so
repetition costs nothing. What it may NOT do is be the only place a good fact
appears. Check each of your cards: is the single most surprising thing in the
sources on one of them?

Each card's `source` line credits that photograph from its record above — do not
attribute a photograph to a person the record does not name.

{cover_rule}
Alt text: under 100 characters, describing what is visibly in the image.

HARD LIMITS — a post that breaks any of these is rejected outright:
  cards    exactly {n_cards}: one cover, then bodies, then one closing.
           Each uses a different photograph. Count before you finish.
  caption  under 1900 characters, counting spaces and hashtags
  source   under 60 characters per card, and never starting with "File:"
  alt      under 100 characters per card
Write short and cut. Do not pad the caption to fill space.""".strip(),
                CARD_SCHEMA, extra_blocks=image_blocks(post_dir, src["images"]))

    print(f"  카드 {len(post['cards'])}장, 캡션 {len(post['caption'])}자")

    # 부탁이 아니라 덮어쓰기다. 투표로 정한 표지가 대본 쪽 판단으로
    # 바뀌면 투표를 한 의미가 없다.
    if cover and post["cards"]:
        before = post["cards"][0].get("image")
        post["cards"][0].update(cover)
        if before != cover["image"]:
            print(f"  [고정] 표지를 투표 결과로 되돌림: {before} → {cover['image']}")

    fixed, problems = tidy(post, {i["file"] for i in src["images"]})
    for line in fixed:
        print(f"  [자동수정] {line}")
    for line in problems:
        print(f"  [한도초과] {line}")
    if problems:
        sys.exit("길이 제한을 넘겼습니다. 다시 실행하면 대개 통과합니다.")

    # ── 4. 검사관 ────────────────────────────────────────────────
    print()
    print("4단계 — 사실 검증")

    written = "\n".join(
        f"[card {n} headline] {c['headline']}\n"
        + (f"[card {n} note] {c['note']}\n" if c.get("note") else "")
        + f"[card {n} source] {c['source']}"
        for n, c in enumerate(post["cards"], 1)
    ) + f"\n\n[caption]\n{post['caption']}"

    check = call(client, CHECKER_SYSTEM, f"""
=== SOURCES ===
{article[:60000]}

=== PHOTOGRAPH RECORDS ===
{records}

=== TEXT TO VERIFY ===
{written}

List every factual claim in the text above and give a verdict for each. Ignore
the <y></y> highlight tags. Skip pure rhetoric ("nobody knows") that makes no
checkable assertion.""".strip(), CHECK_SCHEMA,
                 extra_blocks=image_blocks(post_dir, src["images"]))

    bad = [c for c in check["claims"] if c["verdict"] != "supported"]
    for c in bad:
        mark = "모순" if c["verdict"] == "contradicted" else "근거없음"
        print(f"  [{mark}] {c['where']}: {c['claim']}")
    print(f"  주장 {len(check['claims'])}개 중 {len(bad)}개 문제")

    # ── 5. 저장 ──────────────────────────────────────────────────
    post["slug"] = slug
    post["handle"] = src.get("handle", "@theglassnegative")
    post["image_dir"] = "img"
    for n, card in enumerate(post["cards"], 1):
        card["file"] = f"card{n}.png"

    with open(os.path.join(post_dir, "post.json"), "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)

    with open(os.path.join(post_dir, "check.json"), "w", encoding="utf-8") as f:
        json.dump({"claims": check["claims"], "problems": len(bad)},
                  f, ensure_ascii=False, indent=2)

    print()
    if bad:
        print(f"완료 — 다만 확인이 필요한 주장이 {len(bad)}개 있습니다.")
        print("승인 화면에 표시됩니다. 그대로 올리지 마세요.")
    else:
        print("완료 — 모든 주장이 자료로 뒷받침됩니다.")


if __name__ == "__main__":
    main()
