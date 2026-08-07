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

# 카드를 세로 가운데(285)에 두면 설명글과 출처 줄이 인스타 UI 밑으로
# 들어간다. 릴스는 아래쪽 400px 남짓을 캡션·계정 이름·단추가 덮는다.
# 위로 올려 붙여서 그 아래를 비워둔다.
CARD_TOP = 150

# 처음 만든 것이 71초였다. 내레이션이 카드 문구를 통째로 읽은 탓인데,
# 그 글은 화면에 이미 떠 있다. 소리로 또 읽으면 길기만 하고 새로 주는
# 것이 없다. 제목만 읽고 설명은 눈으로 읽게 두면 30초 안팎이 된다.
MIN_HOLD = 3.6             # 내레이션이 짧아도 이만큼은 보여준다
MAX_HOLD = 14.0            # 한 장면이 이보다 길면 넘겨버린다
GAP = 1.0                  # 제목을 읽고 설명으로 넘어가기 전 여운
TAIL = 0.9                 # 말이 끝난 뒤 여운
ZOOM_PER_CLIP = 0.06       # 한 장면에서 6% 천천히 확대
FPS = 30

# 중저음 남자 목소리. 억양을 바꿔가며 시험할 수 있게 이름을 붙여둔다.
# 기록 다큐는 영국식이 "진짜배기"로 들리는 관습이 있고, 짧은 영상 피드는
# 미국식이 압도적이라 영국식이 오히려 눈에 띈다. 어느 쪽이 나은지는
# 만들어 들어보고 정할 일이다.
VOICES = {
    "uk": "en-GB-ThomasNeural",       # 영국 남성, 낮고 차분하다
    "us": "en-US-ChristopherNeural",  # 미국 남성, 가장 굵다
    "uk-ryan": "en-GB-RyanNeural",    # 처음 쓰던 목소리. 조금 높다
    "us-guy": "en-US-GuyNeural",
}
RATE = "+6%"
PITCH = "-8Hz"             # 더 낮게 깐다


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        # 무엇이 틀렸는지 안 보이면 고칠 수가 없다. ffmpeg 도 edge-tts 도
        # 쓸모있는 말은 전부 stderr 에 적는다.
        sys.exit(f"[실패] {' '.join(cmd[:4])} … 가 {r.returncode} 로 끝났습니다.\n"
                 f"{(r.stderr or r.stdout)[-1200:]}")
    return r


def have(prog):
    return shutil.which(prog) is not None


def shortlist(post_dir, cards, want):
    """릴스에 쓸 카드만 고른다. 표지와 마무리는 반드시 남긴다.

    무엇을 뺄지는 독자들이 이미 답해뒀다. readers.json 에 각자 꼽은
    '가장 약한 카드' 번호가 있다. 표를 많이 받은 순서로 뺀다. 반응이
    없으면 뒤에서부터 뺀다 — 대본은 앞쪽에 센 것을 놓게 쓰여 있다.

    표지를 빼면 독자 투표로 정한 표지가 무의미해지고, 마무리를 빼면
    표지가 던진 질문에 답이 없는 영상이 된다. 그래서 둘은 건드리지 않는다.
    """
    if want <= 0 or want >= len(cards):
        return list(range(len(cards)))

    keep = {0, len(cards) - 1}
    middle = [i for i in range(len(cards)) if i not in keep]

    votes = {}
    path = os.path.join(post_dir, "readers.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for r in json.load(f).get("readers", []):
                n = r.get("weakest_card")
                if isinstance(n, int) and 1 <= n <= len(cards):
                    votes[n - 1] = votes.get(n - 1, 0) + 1

    # 약하다는 표를 많이 받은 것부터, 같으면 뒤쪽부터 뺀다
    middle.sort(key=lambda i: (-votes.get(i, 0), -i))
    dropped = middle[:len(cards) - want]
    if dropped:
        print("  뺀 카드: " + ", ".join(
            f"{i + 1}번({votes.get(i, 0)}표)" for i in sorted(dropped)))
    return sorted(set(range(len(cards))) - set(dropped))


def spoken(card, full=True):
    """카드에서 읽어줄 말을 제목과 설명으로 나눠 돌려준다.

    한 덩어리로 읽히면 제목이 끝나자마자 설명이 붙어 숨 쉴 틈이 없다.
    따로 만들어 사이를 벌린다. 강조 표시는 소리에 없다.
    """
    head = card["headline"].replace("<y>", "").replace("</y>", "").strip()
    if head and not head.endswith((".", "?", "!")):
        head += "."
    note = (card.get("note") or "").strip() if full else ""
    return head, note


def frame_for(card_path, photo_path, out_path):
    """1080x1350 카드를 1080x1920 화면에 앉힌다.

    배경은 카드가 아니라 그 카드가 쓴 **원본 사진**으로 깐다. 카드를
    늘려서 깔았더니 카드 아래쪽 검은 글상자가 그대로 늘어나 밋밋한
    어두운 띠가 됐다. 원본 사진을 쓰면 위아래가 사진의 연장으로 읽힌다.

    카드는 가운데가 아니라 위로 올려 붙인다. 릴스는 화면 아래쪽을
    인스타가 캡션·계정 이름·단추로 덮는다. 가운데에 두면 설명글과
    출처 줄이 그 밑으로 들어간다.
    """
    card = Image.open(card_path).convert("RGB")
    if card.size != (CARD_W, CARD_H):
        card = card.resize((CARD_W, CARD_H), Image.LANCZOS)

    source = Image.open(photo_path).convert("RGB") if photo_path else card
    scale = max(W / source.width, H / source.height) * 1.1
    bg = source.resize((int(source.width * scale), int(source.height * scale)),
                       Image.LANCZOS)
    left = (bg.width - W) // 2
    top = (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(42))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.5)

    bg.paste(card, (0, CARD_TOP))
    bg.save(out_path, quality=95)


def narrate(text, out_mp3, voice):
    """edge-tts 로 읽힌다. 열쇠도 돈도 필요 없다.

    --pitch 는 반드시 붙여 써야 한다. 값이 빼기로 시작하면 떼어 쓴 순간
    edge-tts 가 그것을 또 다른 옵션으로 읽고 죽는다.
    """
    run([sys.executable, "-m", "edge_tts", "--voice", voice,
         f"--rate={RATE}", f"--pitch={PITCH}",
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
    ap.add_argument("--headline-only", action="store_true",
                    help="설명은 읽지 않는다. 25초쯤으로 짧아진다")
    ap.add_argument("--voice", default="uk", choices=sorted(VOICES),
                    help="목소리. uk=영국 중저음, us=미국 중저음")
    ap.add_argument("--cards", type=int, default=0,
                    help="릴스에 쓸 카드 수. 0이면 전부")
    ap.add_argument("--out", default="reel.mp4")
    args = ap.parse_args()
    voice = VOICES[args.voice]

    for prog in ("ffmpeg", "ffprobe"):
        if not have(prog):
            sys.exit(f"[실패] {prog} 가 없습니다.")

    post_dir = os.path.join(ROOT, "posts", args.slug)
    with open(os.path.join(post_dir, "post.json"), encoding="utf-8") as f:
        post = json.load(f)

    work = os.path.join(post_dir, "reel_work")
    os.makedirs(work, exist_ok=True)

    chosen = shortlist(post_dir, post["cards"], args.cards)
    clips, voices, holds = [], [], []
    for n, idx in enumerate(chosen, 1):
        card = post["cards"][idx]
        card_png = os.path.join(post_dir, card["file"])
        if not os.path.exists(card_png):
            sys.exit(f"[실패] 카드 그림이 없습니다: {card['file']}")

        photo = os.path.join(post_dir, "img", card.get("image", ""))
        if not os.path.exists(photo):
            photo = None      # 원본이 없으면 카드로 대신한다

        frame = os.path.join(work, f"frame{n}.jpg")
        frame_for(card_png, photo, frame)

        hold, said = MIN_HOLD, []
        if not args.no_tts:
            head_text, note_text = spoken(card, not args.headline_only)

            head_mp3 = os.path.join(work, f"head{n}.mp3")
            narrate(head_text, head_mp3, voice)
            said.append((head_mp3, 0.0))
            at = duration(head_mp3)

            if note_text:
                # 제목이 끝나고 한 박자 쉰다. 붙여 읽으면 숨 쉴 틈이 없고,
                # 화면의 제목을 눈으로 따라잡을 시간도 없다.
                at += GAP
                note_mp3 = os.path.join(work, f"note{n}.mp3")
                narrate(note_text, note_mp3, voice)
                said.append((note_mp3, at))
                at += duration(note_mp3)

            hold = min(MAX_HOLD, max(MIN_HOLD, at + TAIL))
        holds.append(hold)
        voices.append(said)

        out = os.path.join(work, f"clip{n}.mp4")
        clip(frame, hold, out)
        clips.append(out)
        print(f"  카드 {idx + 1}: {hold:.1f}초")

    listing = os.path.join(work, "clips.txt")
    with open(listing, "w", encoding="utf-8") as f:
        for c in clips:
            f.write(f"file '{os.path.basename(c)}'\n")

    silent = os.path.join(work, "silent.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing,
         "-c", "copy", silent])

    out_mp4 = os.path.join(post_dir, args.out)
    if args.no_tts:
        shutil.move(silent, out_mp4)
    else:
        # 소리 토막마다 절대 시각을 계산해 얹는다. 이어붙이면 화면과
        # 조금씩 어긋나서 뒤로 갈수록 말이 늦는다.
        inputs, filters, labels, scene_at, k = ["-i", silent], [], [], 0.0, 0
        for said, hold in zip(voices, holds):
            for mp3, offset in said:
                ms = int((scene_at + offset) * 1000)
                inputs += ["-i", mp3]
                k += 1
                filters.append(f"[{k}:a]adelay={ms}|{ms}[a{k}]")
                labels.append(f"[a{k}]")
            scene_at += hold
        filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0[out]")
        run(["ffmpeg", "-y"] + inputs +
            ["-filter_complex", ";".join(filters),
             "-map", "0:v", "-map", "[out]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
             "-shortest", out_mp4])

    # 첫 장면은 남겨둔다. 영상을 다 보지 않고도 화면 구성이 맞는지
    # 확인할 수 있어야 한다.
    shutil.copy(os.path.join(work, "frame1.jpg"),
                os.path.join(post_dir, "reel_cover.jpg"))

    total = sum(holds)
    size = os.path.getsize(out_mp4) / 1_000_000
    print(f"완료 — {out_mp4}  {total:.1f}초  {size:.1f}MB")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
