"""
모델에 무언가를 보내고 답을 꺼내는 공용 함수들.

여기 모아둔 이유는 같은 실수를 여러 파일에서 반복했기 때문이다.

  answer_of  — 처음엔 각 스크립트가 next(b.text for b in r.content) 한 줄로
               답을 꺼냈다. 답이 안 오면 StopIteration 만 남아서 자동 실행
               기록에 무엇이 잘못됐는지가 안 남았다.
  sniff      — 처음엔 파일 확장자로 그림 종류를 정했다. 위키미디어 축소본은
               주소가 .jpg 로 끝나도 원본이 GIF면 GIF를 준다. 세 파일이
               똑같이 틀리고 있었다.

매일 아침 사람 없이 도는 것은 실패할 때 이유를 남겨야 한다.
"""

import base64
import json

MODEL = "claude-opus-5"

# 파일 첫머리 몇 바이트로 그림 종류를 알아낸다. (표식, 종류)
MAGIC = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
]


def sniff(blob):
    """그림 종류를 내용으로 판단한다. 모르면 None."""
    for magic, media in MAGIC:
        if blob[:len(magic)] == magic:
            return media
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return None


def block_from(blob):
    """받아온 그림 데이터를 모델에 보낼 형태로. 종류를 모르면 None."""
    media = sniff(blob)
    if not media:
        return None
    return {"type": "image", "source": {
        "type": "base64", "media_type": media,
        "data": base64.standard_b64encode(blob).decode()}}


# 모델에 보낼 때만 줄이는 크기. 저장된 원본은 그대로 둔다 — 카드를
# 그릴 때는 확대 크롭까지 견뎌야 하므로 2400픽셀이 필요하다.
#
# 2026-08-10, 표지 후보를 뽑다가 413 Request exceeds the maximum size 로
# 죽었다. 2400픽셀 원본 여섯 장을 그대로 보내고 있었다. 무엇이 찍혔는지
# 보고 판단하는 데는 이 크기면 넉넉하다.
MAX_SIDE = 1400
JPEG_QUALITY = 82
SMALL_ENOUGH = 900_000     # 이보다 작으면 굳이 손대지 않는다


def shrink(blob, max_side=MAX_SIDE):
    """모델에 보낼 그림을 줄인다. 못 줄이면 원본 그대로 돌려준다.

    Pillow 를 여기서 불러온다. 이 파일을 쓰는 워크플로 중에 Pillow 를
    안 까는 것이 있는데(prepare), 그쪽은 이 함수를 안 쓴다. 맨 위에서
    불러오면 그 워크플로가 통째로 죽는다.
    """
    if len(blob) < SMALL_ENOUGH:
        return blob
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(blob))
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_QUALITY)
        return buf.getvalue()
    except Exception:
        return blob


def image_block(path):
    """사진 파일 하나를 모델에 보낼 형태로. 못 읽으면 None."""
    try:
        with open(path, "rb") as f:
            return block_from(shrink(f.read()))
    except OSError:
        return None


def answer_of(r, what):
    """구조화 응답에서 JSON을 꺼낸다. 못 꺼내면 이유를 말하고 예외를 던진다."""
    if r.stop_reason == "refusal":
        raise RuntimeError(f"{what}: 모델이 거부했습니다.")
    if r.stop_reason == "max_tokens":
        raise RuntimeError(f"{what}: 답이 max_tokens 에서 잘렸습니다. "
                           f"한도를 올리거나 물어보는 양을 줄이세요.")
    text = next((b.text for b in r.content if b.type == "text"), None)
    if text is None:
        kinds = ", ".join(b.type for b in r.content) or "(빈 응답)"
        raise RuntimeError(f"{what}: 글자가 없습니다. "
                           f"stop_reason={r.stop_reason}, 블록={kinds}")
    return json.loads(text)
