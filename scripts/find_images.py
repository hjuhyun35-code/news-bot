"""
소재 하나에 쓸 저작권 만료 사진을 찾아 내려받고 source.json 을 만든다.

    python scripts/find_images.py antikythera

순서
  1. 후보 모으기  — 위키백과 문서에 실린 사진 + 위키미디어 검색 결과
  2. 걸러내기     — 저작권 만료가 아니면 버린다. 여기서 안 걸러진 건 없다
  3. 고르기       — 후보 사진을 실제로 보고 4~6장을 고른다
  4. 내려받기     — posts/<slug>/img/ 에 저장
  5. source.json  — 다음 단계(write_post.py)가 읽을 파일

저작권 판단은 코드가 한다. 모델에게 "저작권 만료된 것만 골라줘"라고
부탁하지 않는다. 부탁은 대체로 지켜지지만 대체로는 부족하다.
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

WANT = 5          # 고를 사진 수
MIN_WIDTH = 900   # 이보다 작으면 카드에서 뭉개진다
DOWNLOAD_W = 2400 # 내려받을 가로 크기. 확대 크롭까지 견디는 정도

# 문서마다 딸려오는 장식용 파일들. 사진이 아니다.
JUNK = re.compile(
    r"(commons-logo|wiki\w*-logo|wikidata|wikisource|wikiquote|disambig"
    r"|edit-icon|symbol_|flag_of|coat_of_arms|folder_|_icon|question_book"
    r"|ambox|padlock|red_pencil|nuvola|crystal_clear|gnome-|text_document)",
    re.IGNORECASE)


def get(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def strip(raw):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw or "")).strip()


def is_public_domain(meta):
    """저작권 만료인가. 애매하면 아니라고 답한다.

    위키미디어는 라이선스를 두 군데에 적는다. License 는 기계용 짧은 값
    (pd, cc-by-sa-4.0), LicenseShortName 은 사람용 이름이다. 둘 다 본다.
    """
    code = strip(meta.get("License", {}).get("value", "")).lower()
    name = strip(meta.get("LicenseShortName", {}).get("value", "")).lower()
    if code.startswith("pd") or code in ("cc0", "cc-zero"):
        return True
    return "public domain" in name or name in ("cc0", "cc zero")


def describe(page):
    """사진 한 장의 기록을 우리가 쓰는 형태로 정리한다."""
    info = page["imageinfo"][0]
    meta = info.get("extmetadata", {})

    def field(key):
        return strip(meta.get(key, {}).get("value", ""))

    return {
        "commons": page["title"],
        "description": field("ImageDescription")[:400],
        "date": field("DateTimeOriginal"),
        "author": field("Artist"),
        "license": field("LicenseShortName") or field("License"),
        "width": info.get("width", 0),
        "height": info.get("height", 0),
        "thumb": info.get("thumburl", ""),
        "meta": meta,
    }


def images_in_article(title):
    """문서 본문에 실린 사진들. 가장 관련성이 높다."""
    data = get("https://en.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "redirects": "1",
        "titles": title, "generator": "images", "gimlimit": "100",
    })
    pages = data.get("query", {}).get("pages", {})
    return [p["title"] for p in pages.values()
            if p["title"].lower().startswith("file:")]


def images_by_search(subject, limit=40):
    """위키미디어에서 직접 검색. 문서에 사진이 적을 때 메운다."""
    data = get("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "list": "search",
        "srnamespace": "6", "srlimit": str(limit), "srsearch": subject,
    })
    return [r["title"] for r in data.get("query", {}).get("search", [])]


def records(titles):
    """파일 제목 목록을 받아 기록을 한꺼번에 가져온다. 한 번에 50개씩."""
    out = []
    for i in range(0, len(titles), 50):
        data = get("https://commons.wikimedia.org/w/api.php", {
            "action": "query", "format": "json",
            "titles": "|".join(titles[i:i + 50]),
            "prop": "imageinfo",
            "iiprop": "extmetadata|url|size",
            "iiurlwidth": "500",
        })
        for page in data.get("query", {}).get("pages", {}).values():
            if "imageinfo" in page:
                out.append(describe(page))
    return out


PICKER_SYSTEM = """You choose archive photographs for a six-card Instagram
carousel about unexplained history.

Every candidate shown to you is already cleared for copyright. Your job is
purely editorial: which photographs make the strongest set.

What makes a strong set:
  - one image that works as a cover: a clear, striking subject with room
    around it, readable at thumbnail size on a phone
  - visual variety. A wide view, a detail, a document or drawing, and a
    photograph of people or aftermath all in one set is ideal. Five near
    identical views of the same object is a wasted set.
  - the actual thing, not a modern reconstruction, museum signage, a location
    map, or a portrait of a scholar who studied it, unless that image genuinely
    carries part of the story
  - decent condition. Skip anything so dark, blurred, or damaged that a viewer
    cannot tell what they are looking at.

Reject aggressively. A set of four strong photographs beats six with two duds.

Give each pick a short lowercase filename stem with no extension and no
spaces (tower, patent, demolition, shaft). Name it after what is in the
picture."""

PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "commons": {"type": "string"},
                    "stem": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["commons", "stem", "why"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["picks", "note"],
    "additionalProperties": False,
}


def choose(client, subject, candidates):
    """후보 사진을 모델에게 실제로 보여주고 고르게 한다."""
    blocks = []
    for n, c in enumerate(candidates, 1):
        blocks.append({"type": "text", "text":
                       f"[{n}] {c['commons']}\n"
                       f"    {c['width']}x{c['height']}, {c['date'] or '날짜 미상'}\n"
                       f"    {c['description'][:200] or '(설명 없음)'}"})
        try:
            data = base64.standard_b64encode(fetch(c["thumb"])).decode()
        except Exception as e:            # 썸네일 하나 실패로 전체를 죽이지 않는다
            blocks.append({"type": "text", "text": f"    (미리보기 실패: {e})"})
            continue
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": data}})

    prompt = (f"Subject: {subject}\n\n"
              f"{len(candidates)} candidates are shown above. Choose at most "
              f"{WANT}, in the order you would put them in the carousel. "
              f"Return the `commons` title exactly as written. In `note`, say "
              f"in one sentence what this set is missing, if anything.")

    r = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=PICKER_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": PICK_SCHEMA}},
        messages=[{"role": "user",
                   "content": blocks + [{"type": "text", "text": prompt}]}],
    )
    if r.stop_reason == "refusal":
        sys.exit("[중단] 모델이 이 소재를 거부했습니다.")
    return json.loads(next(b.text for b in r.content if b.type == "text"))


def download(rec, dest):
    """카드에 쓸 크기로 내려받는다. 원본이 작으면 원본을 그대로."""
    meta = rec["meta"]
    url = rec.get("full_url", "")
    if rec["width"] > DOWNLOAD_W:
        data = get("https://commons.wikimedia.org/w/api.php", {
            "action": "query", "format": "json", "titles": rec["commons"],
            "prop": "imageinfo", "iiprop": "url",
            "iiurlwidth": str(DOWNLOAD_W),
        })
        page = next(iter(data["query"]["pages"].values()))
        url = page["imageinfo"][0].get("thumburl") or url
    blob = fetch(url)
    with open(dest, "wb") as f:
        f.write(blob)
    return len(blob)


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/find_images.py <슬러그>")
    slug = sys.argv[1]

    with open(os.path.join(ROOT, "queue.json"), encoding="utf-8") as f:
        subjects = json.load(f)["subjects"]
    item = next((s for s in subjects if s["slug"] == slug), None)
    if not item:
        sys.exit(f"[실패] queue.json 에 '{slug}' 가 없습니다.")

    print(f"소재: {item['subject']}")

    # ── 1. 후보 모으기 ───────────────────────────────────────────
    print("1단계 — 후보 사진 모으기")
    titles = images_in_article(item["wikipedia"])
    print(f"  문서에 실린 사진 {len(titles)}장")

    extra = [t for t in images_by_search(item["subject"]) if t not in titles]
    titles += extra
    print(f"  검색으로 {len(extra)}장 추가")

    titles = [t for t in titles if not JUNK.search(t)
              and not t.lower().endswith((".svg", ".ogg", ".ogv", ".webm",
                                          ".wav", ".mid", ".pdf", ".djvu"))]
    print(f"  장식·비사진 제외 후 {len(titles)}장")

    # ── 2. 걸러내기 ──────────────────────────────────────────────
    print()
    print("2단계 — 저작권 확인")
    all_recs = records(titles[:120])

    good, rejected = [], 0
    for rec in all_recs:
        if not is_public_domain(rec["meta"]):
            rejected += 1
            continue
        if rec["width"] < MIN_WIDTH:
            continue
        if not rec["thumb"]:
            continue
        good.append(rec)

    print(f"  저작권 만료 아님으로 제외 {rejected}장")
    print(f"  크기 미달 제외 {len(all_recs) - rejected - len(good)}장")
    print(f"  남은 후보 {len(good)}장")

    if len(good) < 4:
        sys.exit(f"[중단] 쓸 수 있는 사진이 {len(good)}장뿐입니다. "
                 f"이 소재는 사진이 부족합니다. queue.json 에서 "
                 f"\"hold\": true 로 빼두세요.")

    good = good[:30]   # 30장이면 고르기에 충분하고 비용도 감당된다

    # ── 3. 고르기 ────────────────────────────────────────────────
    print()
    print("3단계 — 고르기")
    result = choose(anthropic.Anthropic(), item["subject"], good)

    by_title = {r["commons"]: r for r in good}
    picks = []
    for p in result["picks"]:
        rec = by_title.get(p["commons"])
        if not rec:
            print(f"  [무시] 후보에 없는 제목: {p['commons']}")
            continue
        picks.append((rec, p))

    if len(picks) < 4:
        sys.exit(f"[중단] 고른 사진이 {len(picks)}장뿐입니다.")

    # ── 4. 내려받기 ──────────────────────────────────────────────
    print()
    print("4단계 — 내려받기")
    img_dir = os.path.join(ROOT, "posts", slug, "img")
    os.makedirs(img_dir, exist_ok=True)

    images, used = [], set()
    for rec, p in picks:
        ext = os.path.splitext(rec["commons"])[1].lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png"):
            ext = ".jpg"
        stem = re.sub(r"[^a-z0-9]+", "", p["stem"].lower())[:20] or "image"
        while stem in used:
            stem += "2"
        used.add(stem)

        name = stem + ext
        # 큰 원본은 축소본을 받는데, 축소본은 항상 jpg 로 나온다
        if rec["width"] > DOWNLOAD_W:
            name = stem + ".jpg"

        # 원본 주소를 받아둔다. 축소가 필요하면 download() 가 알아서 바꾼다
        info = get("https://commons.wikimedia.org/w/api.php", {
            "action": "query", "format": "json", "titles": rec["commons"],
            "prop": "imageinfo", "iiprop": "url",
        })
        page = next(iter(info["query"]["pages"].values()))
        rec["full_url"] = page["imageinfo"][0]["url"]

        kb = download(rec, os.path.join(img_dir, name)) // 1024
        print(f"  {name:22} {kb:>6} KB   {p['why'][:60]}")
        images.append({"file": name, "commons": rec["commons"]})

    # ── 5. source.json ───────────────────────────────────────────
    source = {
        "subject": item["subject"],
        "wikipedia": item["wikipedia"],
        "handle": "@theglassnegative",
        "images": images,
    }
    with open(os.path.join(ROOT, "posts", slug, "source.json"),
              "w", encoding="utf-8") as f:
        json.dump(source, f, ensure_ascii=False, indent=2)

    print()
    if result.get("note"):
        print(f"고르면서 남긴 말: {result['note']}")
    print(f"완료 — 사진 {len(images)}장, posts/{slug}/source.json 작성")


if __name__ == "__main__":
    main()
