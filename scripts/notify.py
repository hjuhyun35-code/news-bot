"""
텔레그램으로 짧은 알림 하나 보내기.

    python scripts/notify.py "오늘 초안 만들기가 실패했습니다"

자동 실행이 실패했을 때 쓴다. 실패가 조용하면 며칠 뒤에야 알게 된다.
"""

import sys

import telegram

if __name__ == "__main__":
    args = sys.argv[1:]

    # --button 을 주면 단추가 달린 시험용 글을 보낸다. 단추를 눌렀는데
    # 아무 일도 안 일어날 때, 어느 봇의 어느 글을 눌렀는지 헷갈리지 않도록
    # 지금 막 보낸 글로 시험하기 위한 것이다.
    button = "--button" in args
    if button:
        args.remove("--button")
    if not args:
        sys.exit("사용법: python scripts/notify.py [--button] \"보낼 글\"")

    buttons = [[("👉 여기를 눌러주세요", "done")]] if button else None
    _, err = telegram.say(" ".join(args), buttons=buttons)
    if err:
        sys.exit(f"[실패] 알림을 보내지 못했습니다: {err}")
    print("단추 달린 시험 글 보냄" if button else "알림 보냄")
