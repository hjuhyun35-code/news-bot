"""
모델 응답에서 답을 꺼내는 공용 함수.

처음엔 각 스크립트에서 next(b.text for b in r.content ...) 한 줄로 꺼냈다.
답이 안 오면 StopIteration 만 남아서, 자동 실행 기록에 무엇이 잘못됐는지가
안 남았다. 매일 아침 사람 없이 도는 것은 실패할 때 이유를 남겨야 한다.
"""

import json

MODEL = "claude-opus-5"


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
