"""
완성된 카드를 독자 다섯 명에게 보여주고 반응을 받는다.

    python scripts/reader_reactions.py cardiff-giant

posts/<slug>/card*.png 를 실제로 보여준다. 사람이 인스타에서 보는 것과
같은 것을 보게 하려는 것이다. 대본이나 자료는 주지 않는다 — 독자는
그걸 못 보니까.

다섯 명은 각각 따로 부른다. 한 번에 다 물으면 서로 눈치를 봐서
"앞 사람 말이 맞다"는 답이 나온다. 작가와 검사관을 따로 부르는 것과
같은 이유다.

사실 검증과 달리 이건 통과/실패가 아니다. 발행을 막지 않는다.
사람이 승인할 때 참고하라고 옆에 놓는 것뿐이다.
"""

import base64
import json
import os
import sys

import anthropic

from llm import answer_of

MODEL = "claude-opus-5"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 이 다섯 명을 고른 기준: 스크롤 속도, 이 장르 경험치, 시각적 눈높이,
# 사실에 대한 예민함이 서로 다르게 겹치도록. 다 비슷한 사람이면
# 다섯 번 물어도 한 번 물은 것과 같다.
READERS = [
    {
        "name": "Maya",
        "age": 19,
        "who": """A university student in Chicago. Instagram and TikTok are the
same thing to her — she scrolls at speed, thumb never stopping, and a post gets
about one second to earn a swipe. She does not read anything that looks like
homework. She loves being told something wild that she can screenshot and send
to a group chat. If the first card does not land instantly she is already gone,
and she will not feel bad about it.""",
    },
    {
        "name": "Daniel",
        "age": 34,
        "who": """A project manager in Manchester who watches history
documentaries in the evening and saves posts to read properly later. He is the
kind of follower this account actually wants: he will read all six cards if the
first one earns it. He is put off by hype and by mystery that turns out to be
nothing, and he notices when a post promises a question and never answers it.""",
    },
    {
        "name": "Sofia",
        "age": 27,
        "who": """A graphic designer in Lisbon. She sees the craft before she
sees the content: type that is too tight, a crop that cuts a subject at the
edge, scan artefacts, two cards that look like the same picture, a colour grade
that has gone muddy. She is not unkind about it, but she cannot unsee it, and
badly made work makes her distrust the account.""",
    },
    {
        "name": "Robert",
        "age": 52,
        "who": """A retired secondary school teacher in Ohio. He reads
carefully and he checks things. Overstated claims annoy him more than boring
ones — "nobody knows" about something that is in fact well understood will make
him comment and correct it publicly. He respects an account that says plainly
what is not known. He is also the person who notices an uncredited photograph.""",
    },
    {
        "name": "Jess",
        "age": 23,
        "who": """Works in a coffee shop in Melbourne and has followed
unexplained-history and true-archive accounts for years. She has seen every
cliche in this genre — the fake cliffhanger, the recycled stock mystery, the
caption that repeats the headline, the "scientists can't explain" framing. She
is bored by what is familiar and genuinely delighted by what is new to her.""",
    },
]

SYSTEM = """You are a real person scrolling Instagram, not a reviewer and not
an assistant. You have been handed the cards of one post from an account you do
not follow, exactly as they would appear in your feed.

React the way you actually would. If you would swipe past the first card, say
so — that is useful information and it is not rude. Do not look for something
nice to say. Do not grade generously because the work is clearly effortful; a
reader in the feed does not know or care how long it took.

You are reading in English. Write your reaction in KOREAN, because the person
who made this reads Korean. Keep it plain and direct — the way you would text a
friend, not the way a critic writes.

Be specific. "표지가 약하다" is useless. "표지 글자가 사진이랑 겹쳐서 1초
안에 안 읽힌다" can be acted on."""

SCHEMA = {
    "type": "object",
    "properties": {
        "first_second": {"type": "string"},
        "action": {"type": "string",
                   "enum": ["그냥 넘김", "몇 장 보다 넘김", "끝까지 봄",
                            "저장함", "팔로우함"]},
        "good": {"type": "string"},
        "bad": {"type": "string"},
        "weakest_card": {"type": "integer"},
        "score": {"type": "integer"},
    },
    "required": ["first_second", "action", "good", "bad",
                 "weakest_card", "score"],
    "additionalProperties": False,
}


def card_blocks(post_dir, cards):
    blocks = []
    for n, card in enumerate(cards, 1):
        path = os.path.join(post_dir, card["file"])
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        blocks.append({"type": "text", "text": f"카드 {n}"})
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/png", "data": data}})
    return blocks


def ask(client, reader, blocks, caption):
    prompt = f"""You are {reader['name']}, {reader['age']}.

{reader['who']}

The {len(blocks) // 2} cards above are one post, in order. Below is its caption,
which sits under the post and needs a tap to read in full.

=== CAPTION ===
{caption}

Answer as yourself:
  first_second  — 표지를 본 1초 동안 머릿속에 든 생각. 한 문장.
  action        — 실제로 어떻게 했을지
  good          — 제일 괜찮았던 것. 없으면 없다고 쓰세요.
  bad           — 제일 걸리는 것. 이게 가장 중요합니다.
  weakest_card  — 가장 약한 카드 번호 (1-6)
  score         — 이 계정을 팔로우할 마음이 드는 정도 1-10.
                  10은 지금 바로 누른다는 뜻입니다. 후하게 주지 마세요."""

    r = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user",
                   "content": blocks + [{"type": "text", "text": prompt}]}],
    )
    return answer_of(r, f"{reader['name']} 반응")


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/reader_reactions.py <슬러그>")
    slug = sys.argv[1]

    post_dir = os.path.join(ROOT, "posts", slug)
    with open(os.path.join(post_dir, "post.json"), encoding="utf-8") as f:
        post = json.load(f)

    blocks = card_blocks(post_dir, post["cards"])
    if not blocks:
        sys.exit("[실패] 카드 이미지가 없습니다. 먼저 render_cards.py 를 돌리세요.")

    client = anthropic.Anthropic()
    out = []
    for reader in READERS:
        # 한 명이 실패해도 나머지 반응은 받는다. 이건 발행을 막는 검사가
        # 아니라 참고 자료이므로, 부분적으로라도 있는 편이 낫다.
        try:
            said = ask(client, reader, blocks, post["caption"])
        except Exception as e:
            print(f"  {reader['name']}: 실패 ({e})")
            continue
        if not said:
            continue
        said["name"] = reader["name"]
        said["age"] = reader["age"]
        out.append(said)
        print(f"  {reader['name']}({reader['age']}) {said['score']}점 "
              f"— {said['action']} — {said['bad'][:60]}")

    if not out:
        sys.exit("[실패] 반응을 하나도 받지 못했습니다.")

    passed = sum(1 for r in out if r["action"] in ("끝까지 봄", "저장함", "팔로우함"))
    avg = round(sum(r["score"] for r in out) / len(out), 1)

    with open(os.path.join(post_dir, "readers.json"), "w", encoding="utf-8") as f:
        json.dump({"readers": out, "average": avg,
                   "read_through": passed, "asked": len(out)},
                  f, ensure_ascii=False, indent=2)

    print()
    print(f"평균 {avg}점 · {len(out)}명 중 {passed}명이 끝까지 봄")


if __name__ == "__main__":
    main()
