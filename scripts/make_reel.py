"""이미 만들어둔 카드로 릴스용 세로 영상을 만든다.

    python scripts/make_reel.py greek-fire
    python scripts/make_reel.py greek-fire --no-tts

posts/<slug>/card*.png 를 그대로 쓴다. 카드는 1080x1350 인데 릴스는
1080x1920 이라, 같은 카드를 크게 늘려 흐리게 깐 배경 위에 원래 카드를
얹는다. 사진을 새로 자르지 않으므로 독자 투표로 정한 표지 구도가
그대로 유지된다.

소리는 TTS 내레이션만 넣는다. 음악은 넣지 않는다 — 인스타는 이미
올라간 릴스의 음원을 바꿔주지 않으므로, 음악은 사장님이 앱에서 올리실
때 직접 고르신다. 그래서 이 스크립트의 결과물은 인스타에 자동으로
올리지 않고 파일로 건넨다.

카드마다 머무는 시간은 내레이션 길이가 정한다. 글자 수로 어림잡으면
짧은 문장에서 화면이 먼저 넘어가 말이 잘린다.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

W, H = 1080, 1920          # 릴스 규격
CARD_W, CARD_H = 1080, 1350
MIN_HOLD = 2.8             # 내레이션이 짧아도 이만큼은 보여준다
TAIL = 0.7                 # 말이 끝난 뒤 여운
ZOOM_PER_CLIP = 0.06       # 한 장면에서 6% 천천히 확대
FPS = 30
VOICE = "en-GB-RyanNeural"


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def have(prog):
    return shutil.which(prog) is not None


def spoken(card):
    """카드에서 읽어줄 말. 강조 표시는 소리에 없다."""
    head = card["headline"].replace("<y>", "").replace("</y>", "").strip()
    note = (card.get("note") or "").strip()
    if head and not head.endswith((".", "?", "!")):
        head += "."
    return f"{head} {note}".strip()


def frame_for(card_path, out_path):
    """1080x1350 카드를 1080x1920 화면에 앉힌다.

    남는 위아래를 검게 두면 영상이 잘린 사진처럼 보인다. 같은 카드를
    화면 가득 늘려 흐리게 깔면 색이 이어져서 한 장면으로 읽힌다.
    """
    card = Image.open(card_path).convert("RGB")
    if card.size != (CARD_W, CARD_H):
        card = card.resize((CARD_W, CARD_H), Image.LANCZOS)

    # 배경: 화면을 채우도록 늘리고 흐리게, 그리고 어둡게
    scale = max(W / card.width, H / card.height) * 1.15
    bg = card.resize((int(card.width * scale), int(card.height * scale)), Image.LANCZOS)
    left = (bg.width - W) // 2
    top = (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(38))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.55)

    bg.paste(card, (0, (H - CARD_H) // 2))
    bg.save(out_path, quality=95)


def narrate(text, out_mp3):
    """edge-tts 로 읽힌다. 열쇠도 돈도 필요 없다."""
    run([sys.executable, "-m", "edge_tts", "--voice", VOICE,
         "--text", text, "--write-media", out_mp3])


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(r.stdout.strip())


def clip(frame, seconds, out_mp4):
    """정지 화면 한 장을 천천히 확대하며 영상으로 만든다."""
    frames = max(2, int(round(seconds * FPS)))
    # zoompan 은 확대할 때 계단이 지므로 먼저 크게 키워두고 줄인다.
    zoom = f"min(1+{ZOOM_PER_CLIP}*on/{frames},{1 + ZOOM_PER_CLIP})"
    run(["ffmpeg", "-y", "-loop", "1", "-i", frame,
         "-vf", (f"scale={W * 2}:{H * 2},"
                 f"zoompan=z='{zoom}':d={frames}:s={W}x{H}:fps={FPS},"
                 f"format=yuv420p"),
         "-t", f"{seconds:.3f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", out_mp4])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--no-tts", action="store_true")
    args = ap.parse_args()

    for prog in ("ffmpeg", "ffprobe"):
        if not have(prog):
            sys.exit(f"[실패] {prog} 가 없습니다.")

    post_dir = os.path.join(ROOT, "posts", args.slug)
    with open(os.path.join(post_dir, "post.json"), encoding="utf-8") as f:
        post = json.load(f)

    work = os.path.join(post_dir, "reel_work")
    os.makedirs(work, exist_ok=True)

    clips, voices, holds = [], [], []
    for n, card in enumerate(post["cards"], 1):
        card_png = os.path.join(post_dir, card["file"])
        if not os.path.exists(card_png):
            sys.exit(f"[실패] 카드 그림이 없습니다: {card['file']}")

        frame = os.path.join(work, f"frame{n}.jpg")
        frame_for(card_png, frame)

        hold = MIN_HOLD
        mp3 = None
        if not args.no_tts:
            mp3 = os.path.join(work, f"voice{n}.mp3")
            narrate(spoken(card), mp3)
            hold = max(MIN_HOLD, duration(mp3) + TAIL)
        holds.append(hold)
        voices.append(mp3)

        out = os.path.join(work, f"clip{n}.mp4")
        clip(frame, hold, out)
        clips.append(out)
        print(f"  카드 {n}: {hold:.1f}초")

    listing = os.path.join(work, "clips.txt")
    with open(listing, "w", encoding="utf-8") as f:
        for c in clips:
            f.write(f"file '{os.path.basename(c)}'\n")

    silent = os.path.join(work, "silent.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing,
         "-c", "copy", silent])

    out_mp4 = os.path.join(post_dir, "reel.mp4")
    if args.no_tts:
        shutil.move(silent, out_mp4)
    else:
        # 내레이션을 장면 시작 시각에 하나씩 얹는다. 이어붙이면 화면과
        # 조금씩 어긋나서 뒤로 갈수록 말이 늦는다.
        inputs, filters, at = ["-i", silent], [], 0.0
        for i, (mp3, hold) in enumerate(zip(voices, holds)):
            inputs += ["-i", mp3]
            filters.append(f"[{i + 1}:a]adelay={int(at * 1000)}|{int(at * 1000)}[a{i}]")
            at += hold
        mix = "".join(f"[a{i}]" for i in range(len(voices)))
        filters.append(f"{mix}amix=inputs={len(voices)}:normalize=0[out]")
        run(["ffmpeg", "-y"] + inputs +
            ["-filter_complex", ";".join(filters),
             "-map", "0:v", "-map", "[out]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
             "-shortest", out_mp4])

    total = sum(holds)
    size = os.path.getsize(out_mp4) / 1_000_000
    print(f"완료 — {out_mp4}  {total:.1f}초  {size:.1f}MB")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
