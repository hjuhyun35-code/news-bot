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


WRITER_SYSTEM = """You write six-card Instagram carousels for @theglassnegative,
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
  2-5 body    — one idea per card. Build toward the answer.
  6  closing  — what remains genuinely unresolved, honestly stated.

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
  grade  — base (dark photographs), paper (documents, drawings, anything on
           paper or vellum), ink (close-ups of handwriting or print),
           cold (wide empty landscapes), warm (fire, heat, explosion),
           deep (the closing card)

The bottom ~340px of a body card is covered by a black caption bar, and the
bottom ~25% of a cover/closing card is darkened for text. Do not put the
subject there.

Vary the images, crops and grades across the six cards. Two cards that look
alike is a wasted card.

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
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "layout": {"type": "string", "enum": ["cover", "body", "closing"]},
                    "image": {"type": "string"},
                    "crop": {"type": "string"},
                    "zoom": {"type": "number"},
                    "grade": {"type": "string",
                              "enum": ["base", "paper", "ink", "cold", "warm", "deep"]},
                    "stamp": {"type": "string"},
                    "headline": {"type": "string"},
                    "note": {"type": "string"},
                    "source": {"type": "string"},
                    "alt": {"type": "string"},
                },
                "required": ["layout", "image", "crop", "zoom", "grade",
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


def tidy(post):
    """길이와 형식은 부탁이 아니라 검사로 지킨다.

    프롬프트에 '60자 이하로' 라고 써도 모델은 자주 넘긴다. 고칠 수 있는 건
    여기서 고치고, 못 고치는 건 실패로 만들어 사람이 보게 한다.
    """
    fixed, problems = [], []
    for n, card in enumerate(post["cards"], 1):
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
        if len(card.get("alt", "")) > ALT_MAX:
            problems.append(f"카드 {n} 대체텍스트가 {len(card['alt'])}자 (한도 {ALT_MAX})")
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

    post = call(client, WRITER_SYSTEM, f"""
Subject: {src['subject']}

=== SOURCE ARTICLE (the only story material you may use) ===
{article[:60000]}

=== PHOTOGRAPH RECORDS (the only thing you may say about the images) ===
{records}

Write the six cards and the caption.

The caption opens with the question people actually type into a search engine
about this subject, then tells the story in short paragraphs, then states plainly
what is still unresolved, then credits the images, then 3-5 hashtags.

Each card's `source` line credits that photograph from its record above — do not
attribute a photograph to a person the record does not name.

Alt text: under 100 characters, describing what is visibly in the image.

HARD LIMITS — a post that breaks any of these is rejected outright:
  caption  under 1900 characters, counting spaces and hashtags
  source   under 60 characters per card, and never starting with "File:"
  alt      under 100 characters per card
Write short and cut. Do not pad the caption to fill space.""".strip(),
                CARD_SCHEMA, extra_blocks=image_blocks(post_dir, src["images"]))

    print(f"  카드 {len(post['cards'])}장, 캡션 {len(post['caption'])}자")

    fixed, problems = tidy(post)
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
checkable assertion.""".strip(), CHECK_SCHEMA)

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
