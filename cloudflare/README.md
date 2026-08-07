# 승인을 즉시 처리하기 — 클라우드플레어 붙이기

## 왜 필요한가

깃허브 예약 실행은 자주 걸러집니다. 시간당 두 번 걸어둔 것이 실제로는
4~6시간에 한 번 돌았습니다. 그래서 승인 단추를 눌러도 몇 시간 뒤에야
반응했습니다. 2026-08-05 에 실제로 겪은 일입니다.

작은 프로그램 하나를 클라우드플레어에 두면, 텔레그램이 단추 눌림을
거기로 곧바로 보내고 그게 깃허브를 즉시 깨웁니다.

```
지금    단추 → 텔레그램에 쌓임 → (깃허브 예약, 4~6시간) → 발행
바꾸면  단추 → 클라우드플레어 → 깃허브 → 발행   (몇 초)
```

덤으로, 텔레그램에 **"오늘꺼 초안"** 이라고 적으면 초안 만들기가 시작됩니다.

## 준비물

- 클라우드플레어 계정 (이미 있습니다 — theroledesk.com 이 거기 있습니다)
- 무료 요금제로 충분합니다

## 1. 깃허브 토큰 만들기

https://github.com/settings/personal-access-tokens/new

- **Token name**: `cloudflare-telegram`
- **Expiration**: 원하는 만큼 (1년 권장)
- **Repository access** → *Only select repositories* → `hjuhyun35-code/news-bot`
- **Permissions** → *Repository permissions* 에서 딱 하나:
  - `Contents` → **Read and write**

다른 권한은 주지 마세요. 이 토큰이 새어나가도 저장소 하나 말고는 할 수
있는 게 없어야 합니다.

> `Contents` 가 **쓰기**여야 하는 게 헷갈리는 지점입니다. 워커가 부르는 것은
> `repository_dispatch` 인데, 이름과 달리 `Actions` 권한이 아니라 `Contents`
> 쓰기 권한을 요구합니다. 2026-08-06 에 `Contents: Read-only` 로 만들었다가
> `403 Resource not accessible by personal access token` 을 받았습니다.

만든 뒤 나오는 `github_pat_...` 값을 복사해둡니다. **한 번만 보여줍니다.**

## 2. 비밀 문자열 하나 정하기

아무 긴 문자열이면 됩니다. 텔레그램과 클라우드플레어만 아는 암호입니다.
예: `gn-2026-8f3a91c7d4e6` — 그대로 쓰지 말고 아무렇게나 바꾸세요.

## 3. 워커 올리기 — 웹사이트에서 (설치 필요 없음)

https://dash.cloudflare.com → 왼쪽 **Compute (Workers)** → **Create** →
**Start with Hello World!** → **Get started**

- 이름을 `glassnegative-telegram` 으로 바꾸고 **Deploy**
- 배포되면 **Edit code** 를 눌러 편집기를 엽니다
- 안에 있던 예제 코드를 **전부 지우고** 이 폴더의 `worker.js` 내용을
  통째로 붙여넣습니다
- 오른쪽 위 **Deploy** 를 다시 누릅니다

그다음 비밀값을 넣습니다. 워커 화면에서
**Settings** → **Variables and Secrets** → **Add**:

| 이름 | 종류 | 값 |
|---|---|---|
| `GITHUB_TOKEN` | Secret | 1번에서 만든 `github_pat_...` |
| `TELEGRAM_SECRET` | Secret | 2번에서 정한 문자열 |

`ALLOWED_CHAT_ID` 는 넣지 않아도 됩니다. 넣고 싶으면 텔레그램 대화
번호를 Secret 으로 추가하세요.

넣은 뒤 **Deploy** 를 한 번 더 눌러야 반영됩니다.

주소는 워커 화면 위쪽에 나옵니다:
`https://glassnegative-telegram.<사장님계정>.workers.dev`

### 명령줄이 편하면

`wrangler` 로도 됩니다. node 설치가 필요합니다.

```bash
npm install -g wrangler
```

그다음 이 폴더에서 `wrangler login`, `wrangler secret put GITHUB_TOKEN`,
`wrangler secret put TELEGRAM_SECRET`, `wrangler deploy` 순서입니다.

## 4. 텔레그램에게 그 주소를 알려주기

아래에서 `<봇토큰>`, `<워커주소>`, `<비밀문자열>` 세 군데를 바꿔서 브라우저
주소창에 넣습니다.

```
https://api.telegram.org/bot<봇토큰>/setWebhook?url=<워커주소>&secret_token=<비밀문자열>&allowed_updates=["message","callback_query"]
```

`{"ok":true,"result":true,"description":"Webhook was set"}` 가 나오면 됩니다.

## 5. 확인

텔레그램에 **오늘꺼 초안** 이라고 보내보세요. 몇 초 안에
"초안을 만들기 시작했습니다" 가 오면 성공입니다.

## 되돌리기

웹훅만 지우면 예전 방식(예약 실행)으로 돌아갑니다. 저장소는 그대로 둬도
됩니다 — `check_approvals.py` 는 웹훅이 있으면 물러나고 없으면 일합니다.

```
https://api.telegram.org/bot<봇토큰>/deleteWebhook
```

## 알아둘 것

- **웹훅과 예약 확인은 같이 못 씁니다.** 텔레그램은 웹훅이 걸리면 소식을
  그쪽으로만 보내고, 예약 실행이 부르는 `getUpdates` 는 오류를 냅니다.
  그래서 `check_approvals.py` 는 웹훅을 발견하면 스스로 물러납니다.
- **워커는 판단하지 않습니다.** 받은 것을 그대로 깃허브에 넘깁니다.
  무엇을 할지는 `scripts/telegram_command.py` 가 정합니다. 규칙을 고칠
  일이 생기면 저장소만 고치면 되고 워커는 손댈 필요가 없습니다.
- **무료 범위**: 하루 10만 요청까지 무료입니다. 이 계정이 하루에 쓰는
  건 많아야 수십 건입니다.
