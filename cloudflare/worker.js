// 텔레그램이 보내는 소식을 받아 깃허브를 곧바로 깨운다.
//
// 왜 있나: 깃허브 예약 실행이 너무 자주 걸러진다. 30분마다 돌게 걸어둔
// 것이 실제로는 4~6시간에 한 번 돌았다. 단추를 눌러도 몇 시간 뒤에야
// 반응하니 쓸 수가 없었다. 여기를 거치면 몇 초다.
//
// 이 워커는 판단을 하지 않는다. 받은 것을 그대로 넘긴다. 무엇을 할지는
// 저장소의 scripts/telegram_command.py 가 정한다 — 그래야 규칙이 코드
// 한 군데에만 있다.
//
// 필요한 비밀값
//   GITHUB_TOKEN     (필수) 저장소 하나에만 쓰는 fine-grained 토큰,
//                    Contents 읽기 + Actions 쓰기. 다른 권한은 주지 말 것.
//   TELEGRAM_SECRET  (필수) 텔레그램에게 웹훅을 걸 때 같이 준 값. 이게
//                    있어야 아무나 이 주소로 가짜 소식을 밀어넣지 못한다.
//   ALLOWED_CHAT_ID  (선택) 텔레그램 대화 번호. 넣으면 그 대화만 통과시킨다.
//                    안 넣어도 된다 — 비밀값 확인이 이미 막고 있고, 저장소
//                    쪽 telegram_command.py 가 주인인지 한 번 더 본다.

const REPO = "hjuhyun35-code/news-bot";

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("이 주소는 텔레그램 웹훅 전용입니다.", { status: 405 });
    }

    // 텔레그램은 웹훅을 걸 때 받은 비밀값을 매번 이 머리글에 담아 보낸다.
    // 안 맞으면 텔레그램이 보낸 것이 아니다.
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TELEGRAM_SECRET) {
      return new Response("아니오", { status: 401 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("읽을 수 없는 내용", { status: 400 });
    }

    // 대화 번호를 넣어뒀다면 그 대화만 넘긴다. 안 넣었으면 이 검사는
    // 건너뛴다 — 위의 비밀값 확인이 이미 남을 막고 있고, 저장소 쪽
    // telegram_command.py 가 주인인지 한 번 더 본다.
    if (env.ALLOWED_CHAT_ID) {
      const chat =
        update?.message?.chat?.id ??
        update?.callback_query?.message?.chat?.id ??
        update?.callback_query?.from?.id;
      if (String(chat) !== String(env.ALLOWED_CHAT_ID)) {
        // 200 을 준다. 오류를 주면 텔레그램이 계속 다시 보낸다.
        return new Response("ok");
      }
    }

    const res = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "glassnegative-telegram-worker",
      },
      body: JSON.stringify({
        event_type: "telegram",
        client_payload: { update },
      }),
    });

    if (!res.ok) {
      // 텔레그램에 오류를 돌려주면 같은 소식을 다시 보낸다. 여기서는
      // 그게 맞다 — 깃허브가 잠깐 죽은 거라면 다시 시도할 값이 있다.
      const body = await res.text();
      console.log(`깃허브 호출 실패 ${res.status}: ${body.slice(0, 300)}`);
      return new Response("깃허브를 부르지 못했습니다", { status: 502 });
    }

    return new Response("ok");
  },
};
