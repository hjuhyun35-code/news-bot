# 핸드오프 — 인스타 자동 발행 환경 (책 요약 계정용)

2026-08-02에 `@theglassnegative` 계정을 세팅하면서 만든 것들.
**책 요약 인스타도 이 환경을 그대로 재사용할 수 있다.** 아래는 다시 만들 필요가 없는 것과,
새 계정에 붙일 때 해야 할 것.

---

## 1. 이미 있는 것 (다시 만들지 말 것)

**Meta 개발자 앱**
- 앱 이름: `glassnegative-bot`
- 방식: **Instagram API with Instagram Login** — 페이스북 *페이지* 불필요
  (페이스북 *계정*은 개발자 사이트 로그인용으로만 씀)
- 이미 켜둔 권한:
  - `instagram_business_basic`
  - `instagram_business_content_publish` ← 게시에 필수
  - `instagram_business_manage_comments`
  - `instagram_business_manage_messages`
- 앱은 **게시(Publish) 안 함 / 심사 안 받음**. 내 계정에만 올리므로 불필요.

**GitHub 저장소**
- `hjuhyun35-code/news-bot` — **Public** (인스타가 카드 이미지를 가져가야 해서)
- 이미 등록된 Secrets:
  `IG_ACCESS_TOKEN`, `IG_USER_ID`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`

**텔레그램 승인 봇**
- `@glassnegative_approve_bot`
- chat id: `8670266291` (비밀 아님)
- 두 계정이 같은 봇을 써도 됨

**검증 완료**
- 6장 캐러셀 발행 성공. 캡션·해시태그·대체텍스트까지 API로 자동 입력됨.

---

## 2. 책 계정을 붙이는 순서 (약 20분)

1. **인스타 계정을 크리에이터로 전환** (개인 계정은 API 불가, 공개 계정이어야 함)
2. `developers.facebook.com` → 앱 `glassnegative-bot` →
   **앱 역할 → 역할 → 더 보기 → Instagram 테스터** → 책 계정 아이디 추가
3. 그 계정으로 `https://www.instagram.com/accounts/manage_access/` 접속 →
   **테스터 초대 → 수락**  (초대는 알림으로 오지 않는다. 이 주소로 직접 가야 함)
4. 앱 → **Instagram 로그인이 포함된 API → 2. 액세스 토큰 생성 → 계정 추가**
   → **책 계정으로 로그인** (개인 계정으로 로그인하면 거기 글이 올라감)
5. 나온 토큰을 GitHub Secrets에 **다른 이름으로** 추가 (예: `IG_TOKEN_BOOKS`)

토큰 확인:
`https://graph.instagram.com/me?fields=id,username&access_token=토큰`
→ 책 계정 아이디가 나오면 성공.

---

## 3. 코드 구조 (그대로 복사해서 쓰면 됨)

```
posts/<슬러그>/
    card1.png ... cardN.png     1080x1350
    post.json                   캡션 + 카드별 대체텍스트
scripts/ig_publish.py           캐러셀 발행
.github/workflows/ig-publish.yml  수동 실행 (slug, confirm 입력)
```

`post.json` 형태:
```json
{
  "slug": "...",
  "caption": "첫 줄에 검색어를 넣을 것. 해시태그는 3~5개면 충분",
  "cards": [{ "file": "card1.png", "alt": "100자 이내" }]
}
```

**안전장치:** 워크플로의 `confirm` 칸에 정확히 `PUBLISH`를 넣어야 실제로 올라감.
다른 값이면 발행 직전까지만 해보고 멈춤(예행연습).

`ig_publish.py`는 계정 아이디를 `me`로 쓰고, 스크립트 안에 계정명 확인이 하드코딩돼 있음
(`theglassnegative`). **책 계정용으로 복사할 때 그 부분과 토큰 환경변수명을 바꿔야 함.**

**카드 만드는 법:** HTML/CSS로 1080x1350 카드를 만들고
헤드리스 엣지로 PNG를 뽑음 (윈도우에 기본 설치돼 있어 추가 설치 불필요):
```
msedge.exe --headless=new --disable-gpu --hide-scrollbars
  --window-size=1080,1350 --virtual-time-budget=9000
  --screenshot="out.png" "file:///.../card.html?card=1"
```
AI 이미지 생성보다 훨씬 낫다. 글자가 정확하고 매번 똑같이 나온다.

---

## 4. 하다가 걸렸던 것들 (반복하지 말 것)

- **GitHub `Create new file`은 지금 보고 있는 폴더 기준으로 만든다.**
  하위 폴더 안에서 `posts/x/y.json`을 치면 `현재폴더/posts/x/y.json`이 된다.
  **반드시 저장소 첫 화면(root)에서 만들 것.**
- **BotFather 가짜가 많다.** 이름은 베낄 수 있으니 **아이디(@)와 파란 인증 배지**로 확인.
  진짜는 정확히 `@BotFather`.
- **`계정 추가` 전에 Instagram 테스터 등록 + 수락이 안 되어 있으면**
  「개발자 역할 권한 부족」 오류가 난다.
- **토큰은 채팅에 붙여넣지 말 것.** 노출되면 BotFather `/revoke`,
  인스타는 앱에서 재발급. GitHub Secrets에 직접 넣으면 AI가 값을 볼 일이 없다.
- **대체텍스트는 100자 이내로.** 길면 컨테이너 생성이 거부될 수 있다.
- **인스타 ID가 두 종류다.** Meta 화면에 보이는 번호와
  `graph.instagram.com/me`가 주는 번호가 다르다. 둘 다 정상.
- **토큰은 60일마다 만료된다.** 자동 갱신을 넣지 않으면 두 달 뒤 조용히 멈춘다.
  (아직 안 넣었음 — 양쪽 계정 모두 해당)

---

## 5. 책 요약 계정에서 다를 점

`@theglassnegative`는 **저작권 만료된 아카이브 사진**으로 이미지 문제를 풀었다.
책 계정은 그 방법이 안 통한다.

- **책 표지 이미지는 저작권이 있다** (출판사 자산)
- **긴 인용도 문제가 된다**
- **줄거리·핵심 아이디어 요약 자체는 괜찮다** — 사실과 아이디어에는 저작권이 없다

→ 이미지를 어떻게 할지가 그 계정의 핵심 설계 문제. 타이포그래피 중심 디자인이나
직접 만든 그래픽으로 가는 게 안전하다.

---

## 6. 참고: 노출 관련해서 확인한 것 (2026년 기준)

- **2025년 7월부터 구글이 인스타 공개 게시물을 색인한다.** 프로 계정이면 검색에 뜬다.
- **해시태그는 이제 거의 의미 없다.** 3~5개면 충분하고 30개 도배는 손해.
  대신 **캡션 첫 줄에 실제 검색어**를 넣는 게 훨씬 중요하다.
- **대체텍스트를 인스타 검색이 읽는다.** 그런데 대부분 안 채운다. 공짜 점수.
- **이미지 위의 큰 글자도 읽힌다.** 카드뉴스 형식이 유리한 이유.
- **새 계정이 처음부터 하루 여러 개를 규칙적으로 올리면 스팸으로 걸린다.**
  2주쯤 사람처럼 쓰다가 천천히 늘릴 것.
