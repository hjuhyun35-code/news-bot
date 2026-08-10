"""사장님이 텔레그램에 적은 대로 대본을 고친다.

    python scripts/apply_edit.py turin-shroud "1번 카드 제목을 더 세게"

대본만 고친다. 사진은 그대로 둔다 — 사진을 바꾸려면 소재를 다시 만드는
편이 빠르고, 표지는 독자 투표로 정한 것이라 함부로 건드리면 안 된다.

고친 뒤에도 검사는 그대로 받는다. 사람이 시킨 말이라고 해서 길이 제한이나
사실 확인을 건너뛰면, 고치다가 계정이 망가진다. 특히 사실 확인은 여기서
가장 중요하다 — "더 세게 써줘"가 없는 사실을 지어내라는 뜻이 되기 쉽다.
"""

import json
import os
import sys

import anthropic

from llm import answer_of
from write_post import (CARD_SCHEMA, MODEL, WRITER_SYSTEM,
                        commons_record, image_blocks, tidy, wikipedia_extract)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EDIT_SYSTEM = WRITER_SYSTEM + """

YOU ARE EDITING AN EXISTING POST, NOT WRITING A NEW ONE.

Return the whole post with the requested change applied and everything else
left exactly as it was. Do not rewrite cards the instruction did not mention.
Do not reorder cards. Do not change which photograph a card uses, or its crop,
zoom, fit or grade — those were chosen by looking at the pictures.

If the instruction asks for something the sources do not support, do not invent
it. Make the smallest honest change you can and say nothing about it here.
"""


def main():
    if len(sys.argv) < 3:
        sys.exit("사용법: python scripts/apply_edit.py <슬러그> <고칠 내용>")
    slug, instruction = sys.argv[1], " ".join(sys.argv[2:])

    post_dir = os.path.join(ROOT, "posts", slug)
    with open(os.path.join(post_dir, "post.json"), encoding="utf-8") as f:
        post = json.load(f)
    with open(os.path.join(post_dir, "source.json"), encoding="utf-8") as f:
        src = json.load(f)

    print(f"소재: {slug}")
    print(f"시키신 것: {instruction}")

    article = wikipedia_extract(src["wikipedia"])
    records = []
    for img in src["images"]:
        rec = commons_record(img["commons"])
        rec.pop("meta", None)
        rec["file"] = img["file"]
        records.append(rec)

    client = anthropic.Anthropic()
    prompt = f"""
=== SOURCE ARTICLE (the only story material you may use) ===
{article[:60000]}

=== PHOTOGRAPH RECORDS (the only thing you may say about the images) ===
{json.dumps(records, ensure_ascii=False, indent=2)}

=== THE POST AS IT STANDS ===
{json.dumps(post, ensure_ascii=False, indent=2)}

=== WHAT THE OWNER ASKED FOR, IN KOREAN ===
{instruction}

Apply that change and return the whole post. Keep the same number of cards and
the same photograph on each card. Obey the same hard limits as before:
caption under 1900 characters, source under 60 characters per card, alt under
100 characters per card.
""".strip()

    post = answer_of(client.messages.create(
        model=MODEL, max_tokens=16000, system=EDIT_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": CARD_SCHEMA}},
        messages=[{"role": "user", "content":
                   image_blocks(post_dir, src["images"])
                   + [{"type": "text", "text": prompt}]}],
    ), "고치기")

    fixed, problems = tidy(post, {i["file"] for i in src["images"]})
    for line in fixed:
        print(f"  [자동수정] {line}")
    if problems:
        for line in problems:
            print(f"  [한도초과] {line}")
        sys.exit("[중단] 고친 결과가 한도를 넘겼습니다. 원본을 그대로 둡니다.")

    with open(os.path.join(post_dir, "post.json"), "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)
    print("대본을 고쳤습니다.")


if __name__ == "__main__":
    main()
