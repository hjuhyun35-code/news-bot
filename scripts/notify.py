"""
텔레그램으로 짧은 알림 하나 보내기.

    python scripts/notify.py "오늘 초안 만들기가 실패했습니다"

자동 실행이 실패했을 때 쓴다. 실패가 조용하면 며칠 뒤에야 알게 된다.
"""

import sys

import telegram

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("사용법: python scripts/notify.py \"보낼 글\"")
    _, err = telegram.say(" ".join(sys.argv[1:]))
    if err:
        sys.exit(f"[실패] 알림을 보내지 못했습니다: {err}")
    print("알림 보냄")
