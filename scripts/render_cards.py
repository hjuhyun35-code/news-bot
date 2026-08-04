"""
posts/<slug>/post.json 을 읽어 카드 PNG를 만든다.

카드마다 HTML을 하나 만들고 헤드리스 크롬으로 1080x1350 스크린샷을 찍는다.
윈도우(엣지)와 리눅스(크로미움) 양쪽에서 같은 결과가 나오도록
글꼴은 저장소에 넣은 파일만 쓴다.

    python scripts/render_cards.py voynich
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

W, H = 1080, 1350
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "design", "fonts")


def find_browser():
    """윈도우면 엣지, 리눅스면 크로미움."""
    candidates = [
        os.environ.get("CHROME_PATH"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        shutil.which("chromium-browser"),
        shutil.which("chromium"),
        shutil.which("google-chrome"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys.exit("[실패] 크롬/엣지/크로미움을 찾지 못했습니다.")


# 사진 성격에 따라 색을 다르게 입힌다.
# (필터, 색조 그라데이션, 색조 세기)
#
# 대비를 세게 걸고 싶은 유혹이 있다. 그러면 사진이 강렬해 보인다.
# 그런데 원래 대비가 약한 기록사진 — 1910년 신문사 인화지 같은 것 — 에
# contrast(2)를 걸면 중간 톤이 전부 죽고 순검정과 순흰색만 남는다.
# 피사체가 사라져서 네거티브 필름처럼 보인다. 독자 다섯 명 중 넷이
# 여러 판에 걸쳐 "이게 뭘 찍은 건지 모르겠다"고 한 원인이 이것이었다.
# 색은 분위기를 주는 것이지 형체를 지우는 것이 아니다.
GRADES = {
    # 어두운 기록사진. 그림자는 푸르게, 하이라이트는 호박색으로
    "base": ("grayscale(1) contrast(1.35) brightness(.96)",
             "linear-gradient(165deg,#1B3A6B 0%,#2E4668 42%,#7A4A16 100%)", .55),
    # 종이나 양피지. 원래 색을 살리고 살짝만 든다
    "paper": ("contrast(1.16) saturate(1.14) brightness(1.03)",
              "linear-gradient(160deg,#6B5A2E,#2E4470)", .14),
    # 잉크 세부. 차갑게, 대비 높게
    "ink": ("contrast(1.5) saturate(.72) brightness(1.0)",
            "linear-gradient(150deg,#1D3556,#2B4A72)", .40),
    # 넓고 빈 풍경. 창백한 한기
    "cold": ("grayscale(1) contrast(1.28) brightness(1.02)",
             "linear-gradient(180deg,#2C4E7A,#4A6E92)", .48),
    # 열이나 폭발. 호박색
    "warm": ("grayscale(1) contrast(1.4) brightness(.98)",
             "linear-gradient(150deg,#8A4A10 0%,#B06A14 55%,#3A2A44 100%)", .62),
    # 마무리 카드. 가장 어둡게
    "deep": ("contrast(1.18) saturate(.9) brightness(.74)",
             "linear-gradient(170deg,#0B1C38,#1E3350)", .52),
}

CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
@font-face { font-family:'CardDisplay'; src:url('{{FONTS}}/Anton-Regular.ttf'); }
@font-face { font-family:'CardBody';    src:url('{{FONTS}}/Inter-Regular.ttf'); }
@font-face { font-family:'CardMono';    src:url('{{FONTS}}/JetBrainsMono.ttf'); }

html, body { width:1080px; height:1350px; overflow:hidden; background:#000; }
.card { width:1080px; height:1350px; background:#000; position:relative;
        display:flex; flex-direction:column; overflow:hidden; }

.stage { position:relative; flex:1; overflow:hidden; background:#0B0C10;
         isolation:isolate; }
.stage > img { width:100%; height:100%; object-fit:cover; display:block;
               filter:{{FILTER}}; transform:scale({{ZOOM}});
               object-position:{{CROP}}; }

/* 가로로 긴 사진을 통째로 보여줄 때.
   뒤에는 같은 사진을 흐리게 깔아 빈 자리를 메우고, 앞에 원본 전체를 얹는다.
   누워 있는 사람처럼 가로로 뻗은 피사체는 세로 카드에 잘라 넣으면
   몸통 한 조각만 남아서 무엇인지 알 수 없게 된다. */
.stage > img.back { position:absolute; inset:0; object-fit:cover;
                    transform:scale(1.2); filter:{{FILTER}} blur(38px)
                    brightness(.3) saturate(.7); }
.stage > img.whole { position:absolute; inset:0; object-fit:contain;
                     transform:none; object-position:50% 42%; }
.grade { position:absolute; inset:0; z-index:2; mix-blend-mode:color;
         background:{{TINT}}; opacity:{{TINTOP}}; }
.burn  { position:absolute; inset:0; z-index:2; pointer-events:none;
         background:linear-gradient(to bottom, rgba(0,0,0,.42) 0%, rgba(0,0,0,0) 22%,
                   rgba(0,0,0,.26) 70%, rgba(0,0,0,.74) 100%); }

.src { position:absolute; left:0; right:0; bottom:0; z-index:5;
       padding:46px 26px 15px;
       background:linear-gradient(to top, rgba(0,0,0,.82), rgba(0,0,0,0));
       font:400 19px/1.3 'CardMono', monospace; letter-spacing:.06em;
       color:rgba(255,255,255,.78); text-transform:uppercase; }

.cap { font-family:'CardDisplay', sans-serif; color:#fff; text-transform:uppercase;
       text-align:center; line-height:1.0; letter-spacing:.005em; text-wrap:balance; }
.cap y { color:#FFD23F; font-style:normal; }
.stamp { font:400 25px/1 'CardMono', monospace; letter-spacing:.22em;
         color:#FFD23F; text-transform:uppercase;
         border:2px solid #FFD23F; padding:12px 20px; }
.note { font:400 30px/1.45 'CardBody', sans-serif; text-align:center;
        color:rgba(255,255,255,.82); max-width:27ch; }

/* 표지와 마무리 카드는 사진 위에 글자를 얹는다 */
.over { position:absolute; z-index:4; left:0; right:0; bottom:0;
        padding:0 62px 66px; display:flex; flex-direction:column;
        align-items:center; gap:26px; }
.over .cap { font-size:112px; }

/* 본문 카드는 검은 띠에 글자를 넣는다 */
.bar { background:#000; flex:0 0 auto; padding:0 54px 40px;
       display:flex; flex-direction:column; align-items:center;
       justify-content:center; gap:22px; min-height:336px; }
.bar .cap { font-size:70px; }
.bar .note { font-size:29px; }
.foot { font:400 22px/1 'CardMono', monospace; letter-spacing:.14em;
        color:rgba(255,255,255,.42); text-transform:uppercase; }

.cta { font:400 29px/1 'CardMono', monospace; letter-spacing:.12em;
       color:#0A0A0A; background:#FFD23F; padding:16px 26px;
       text-transform:uppercase; margin-top:12px; }
"""


def markup(text):
    """<y>강조</y> 만 허용하고 나머지는 escape 한다."""
    esc = html.escape(text or "")
    return re.sub(r"&lt;(/?)y&gt;", r"<\1y>", esc)


def build_html(card, img_dir, handle, index, total):
    filt, tint, tintop = GRADES.get(card.get("grade", "base"), GRADES["base"])

    # 치환 이름은 서로의 부분 문자열이 되면 안 된다.
    # (TINT 를 먼저 바꾸면 TINTOP 안의 TINT 까지 바뀌어 투명도가 깨진다)
    subs = {
        "{{FONTS}}": Path(FONTS).as_uri(),
        "{{FILTER}}": filt,
        "{{ZOOM}}": str(card.get("zoom", 1)),
        "{{CROP}}": card.get("crop", "50% 50%"),
        "{{TINT}}": tint,
        "{{TINTOP}}": str(tintop),
    }
    css = CSS
    for token, value in subs.items():
        css = css.replace(token, value)

    img = Path(os.path.join(img_dir, card["image"])).as_uri()
    if card.get("fit") == "whole":
        picture = (f'<img class="back" src="{img}">'
                   f'<img class="whole" src="{img}">')
    else:
        picture = f'<img src="{img}">'
    src = markup(card.get("source", ""))
    cap = markup(card.get("headline", ""))
    note = f'<div class="note">{markup(card["note"])}</div>' if card.get("note") else ""
    stamp = f'<div class="stamp">{markup(card["stamp"])}</div>' if card.get("stamp") else ""
    layout = card.get("layout", "body")

    if layout in ("cover", "closing"):
        cta = f'<div class="cta">Follow {handle}</div>' if layout == "closing" else ""
        body = f"""
        <div class="stage">
          {picture}
          <div class="grade"></div><div class="burn"></div>
          <div class="src">{src}</div>
          <div class="over">{stamp}<div class="cap">{cap}</div>{note}{cta}</div>
        </div>"""
    else:
        body = f"""
        <div class="stage">
          {picture}
          <div class="grade"></div><div class="burn"></div>
          <div class="src">{src}</div>
        </div>
        <div class="bar">
          <div class="cap">{cap}</div>{note}
          <div class="foot">{handle} &middot; {index:02d} / {total:02d}</div>
        </div>"""

    return (f"<!doctype html><meta charset='utf-8'><style>{css}</style>"
            f"<div class='card'>{body}</div>")


def shoot(page_html, out_path, browser, tmp):
    """HTML 한 장을 PNG로. 표지 고르기 쪽에서도 이 함수를 쓴다.

    브라우저 실행 옵션이 두 군데로 갈라지면 한쪽만 고쳐서 결과가
    달라진다. 그래서 찍는 자리는 여기 하나뿐이다.
    """
    page = os.path.join(tmp, os.path.basename(out_path) + ".html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(page_html)

    subprocess.run([
        browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--no-sandbox",
        f"--window-size={W},{H}", "--virtual-time-budget=10000",
        f"--screenshot={out_path}", Path(page).as_uri(),
    ], capture_output=True, timeout=180)

    return os.path.getsize(out_path) // 1024 if os.path.exists(out_path) else 0


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/render_cards.py <슬러그>")
    slug = sys.argv[1]

    post_dir = os.path.join(ROOT, "posts", slug)
    spec_path = os.path.join(post_dir, "post.json")
    if not os.path.exists(spec_path):
        sys.exit(f"[실패] {spec_path} 가 없습니다.")

    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    cards = spec["cards"]
    # 앞 단계가 이미 세지만 여기서 한 번 더 막는다. 카드 1장짜리 대본이
    # 통과해 그대로 그려진 적이 있다.
    if not 2 <= len(cards) <= 10:
        sys.exit(f"[실패] post.json 에 카드가 {len(cards)}장입니다. "
                 f"인스타 캐러셀은 2~10장입니다.")

    handle = spec.get("handle", "@theglassnegative")
    img_dir = os.path.join(post_dir, spec.get("image_dir", "img"))
    browser = find_browser()

    print(f"{slug} - 카드 {len(cards)}장")
    print(f"브라우저: {browser}")

    # 임시 HTML은 저장소 안에 만든다. snap으로 설치된 브라우저는
    # /tmp 를 못 읽는 경우가 있다.
    tmp = tempfile.mkdtemp(dir=ROOT, prefix=".render-")
    for i, card in enumerate(cards, 1):
        out = os.path.join(post_dir, f"card{i}.png")
        size = shoot(build_html(card, img_dir, handle, i, len(cards)),
                     out, browser, tmp)
        if size < 60:
            sys.exit(f"[실패] 카드 {i} 가 {size} KB 뿐입니다. "
                     f"사진이나 글꼴을 못 불러온 것 같습니다.")
        print(f"  card{i}.png  {size} KB")

    shutil.rmtree(tmp, ignore_errors=True)
    print("완료")


if __name__ == "__main__":
    main()
