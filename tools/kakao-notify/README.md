# 알림 환경 설정

Claude에게 메일과 카카오톡을 연결하기 위한 설정 모음입니다.
두 채널은 성격이 완전히 다릅니다.

| | 방식 | Claude가 직접 쓸 수 있나 | 설정 시간 |
|---|---|---|---|
| **메일** | claude.ai 커넥터 | 예 — 대화 중 바로 | 약 2분 |
| **카카오톡** | 여기 있는 스크립트 | 아니오 — 내 컴퓨터/서버에서 실행 | 약 10분 |

---

## 1. 메일 — 커넥터 연결 (코드 불필요)

가장 편한 경로입니다. 스크립트도, 토큰 관리도 필요 없습니다.

1. [claude.ai](https://claude.ai) → **설정(Settings)** → **커넥터(Connectors)**
2. **Gmail** 찾아서 **Connect** → 구글 로그인 → 권한 동의
3. 대화창 하단 커넥터 토글에서 해당 채팅에 **활성화**

이후 대화에서 이렇게 쓰시면 됩니다.

> "오늘 안 읽은 메일 요약해줘"
> "김대리한테 온 지난주 메일 찾아서 답장 초안 써줘"

### 알아두실 제약

Gmail 커넥터가 제공하는 도구는 `search_threads`, `get_thread`, `create_draft`,
`list_drafts`, `list_labels` 뿐입니다. **읽기와 초안 작성은 되지만 직접 발송은
안 됩니다.** 초안까지 만들어두면 최종 확인 후 직접 보내는 구조입니다.

Outlook을 함께 쓰신다면 **Superhuman Mail** 커넥터가 Gmail/Outlook을 모두
지원합니다.

---

## 2. 카카오톡 — 나에게 보내기

### 왜 '나에게 보내기'만 되나

카카오는 **개인 대화방을 읽는 API를 제공하지 않습니다.** 어떤 방법으로도
카톡 내용을 Claude가 읽게 만들 수 없습니다. 친구에게 보내는 것도 별도 권한
심사가 필요하고 개인 개발자에게는 거의 승인되지 않습니다.

승인 없이 바로 쓸 수 있는 건 **나에게 보내기** 하나입니다. 대신 이건 알림
용도로는 충분히 쓸모가 있습니다 — 긴 작업이 끝났을 때, 배포가 실패했을 때,
정해진 시각에 요약을 받을 때.

접근성 권한을 이용하는 비공식 자동화 앱들이 있지만 카카오 이용약관 위반이고
계정 정지 사유라 다루지 않았습니다.

### 준비: 카카오 앱 만들기 (1회, 약 5분)

1. [developers.kakao.com](https://developers.kakao.com) 로그인
2. **내 애플리케이션** → **애플리케이션 추가하기** → 앱 이름과 회사명 입력
   (개인이면 본인 이름을 넣으셔도 됩니다)
3. **앱 설정 → 앱 키** → **REST API 키** 복사
4. **제품 설정 → 카카오 로그인** → 활성화 설정 **ON**
5. 같은 화면의 **Redirect URI** 에 아래 주소를 정확히 등록

   ```
   http://localhost:5000/oauth
   ```

6. **제품 설정 → 카카오 로그인 → 동의항목** → **카카오톡 메시지 전송**
   (`talk_message`) 을 **선택 동의**로 설정

> 5번의 주소는 `.env`의 `KAKAO_REDIRECT_URI`와 **글자 하나까지 같아야**
> 합니다. 뒤에 `/`가 붙거나 포트가 다르면 인증이 실패합니다.

### 설치

```bash
cd tools/kakao-notify
pip install -r requirements.txt

cp .env.example .env
# .env를 열어 KAKAO_REST_API_KEY 에 3번에서 복사한 키를 붙여넣으세요
```

### 인증 (1회)

```bash
python3 kakao_auth.py
```

브라우저가 열리면 카카오 로그인 후 동의하면 끝입니다. 리프레시 토큰이
`.kakao_token.json`에 저장되고(파일 권한 `0600`), 이후에는 만료될 때마다
자동으로 갱신되므로 다시 실행할 일이 거의 없습니다.

> 리프레시 토큰 유효기간은 2개월이지만 사용할 때마다 연장됩니다. 두 달 넘게
> 한 번도 안 쓰면 그때만 다시 인증하시면 됩니다.

### 클라우드에 토큰 등록하기

브리핑을 서버나 Claude Code 클라우드에서 자동 실행하려면, 위에서 받은 토큰을
그쪽 환경에도 알려줘야 합니다. **토큰 파일을 복사해 옮길 필요는 없습니다.**

인증 직후 화면에 등록할 내용이 출력되고, 나중에 다시 보시려면:

```bash
python3 kakao_auth.py --show-env
```

```
====================================================================
아래 두 줄을 환경변수로 등록하세요 (그대로 복사).
====================================================================
KAKAO_REST_API_KEY=abc123...
KAKAO_REFRESH_TOKEN=RT-xxxx...
====================================================================
리프레시 토큰 유효기간: 약 60일 (쓸 때마다 자동 연장)
```

이 두 줄을 실행 환경의 **환경변수**로 등록하면 됩니다.

- **일반 서버**: `~/.bashrc`에 `export KAKAO_REFRESH_TOKEN=...` 또는
  systemd 유닛의 `Environment=` 항목
- **로컬에서만 쓸 때**: 등록할 필요 없습니다. `.kakao_token.json`이 알아서 쓰입니다
- **Claude Code 클라우드**: 아래 주의사항을 먼저 읽어주세요

`kakao_env.py`는 환경변수를 파일보다 우선해서 읽습니다. 즉 환경변수만 설정되어
있으면 토큰 파일 없이도 동작합니다.

#### Claude Code 클라우드 환경변수에 넣기 전에

[공식 문서](https://code.claude.com/docs/en/cloud-environments)는 클라우드 환경의
환경변수 항목에 **자격증명을 넣지 말라고 명시**하고 있습니다.

> Anyone who uses the environment can read the values, and cloud environments have
> no dedicated secrets store, so don't add API keys or other credentials.

리프레시 토큰은 자격증명입니다. 별도의 비밀 저장소가 없으므로, 넣는다면 이
경고를 알고 넣는 것입니다.

**이 토큰에 한정한 실제 위험도**는 낮은 편입니다. 권한이 `talk_message` 하나뿐이라
유출돼도 할 수 있는 일이 **본인에게 카톡을 보내는 것**뿐입니다. 대화를 읽거나,
친구에게 보내거나, 계정 정보를 가져갈 수 없습니다. 개인 환경(조직 공유 환경이
아닌)이라면 값을 읽을 수 있는 사람도 본인뿐입니다.

그래도 자격증명을 두고 싶지 않으시면 **로컬 cron**으로 돌리세요. 토큰이 컴퓨터
밖으로 나가지 않습니다. 대신 실행 시각에 컴퓨터가 켜져 있어야 합니다.

> 어느 쪽이든 리프레시 토큰을 **채팅창이나 저장소에 붙여넣지 마세요.**
> 유출됐다면 [카카오 계정 → 연결된 서비스 관리](https://accounts.kakao.com)에서
> 앱 연결을 끊으면 즉시 무효화됩니다.

#### 등록 위치 (claude.ai/code)

1. [claude.ai/code](https://claude.ai/code) 접속
2. **메시지 입력창 바로 위 줄**에 환경 이름이 적힌 클라우드 버튼이 있습니다
   (처음이면 `Default`)
3. 그 버튼을 누르면 메뉴가 열립니다. **Cloud** 섹션의 환경 위에 마우스를 올리면
   오른쪽에 **톱니바퀴 아이콘**이 나타납니다. 그걸 누르세요
4. 다이얼로그에 네 가지가 있습니다 — 이름, **Network access**,
   **Environment variables**, Setup script
5. **Environment variables** 칸에 `.env` 형식으로 한 줄에 하나씩 붙여넣습니다

   ```
   KAKAO_REST_API_KEY=abc123...
   KAKAO_REFRESH_TOKEN=RT-xxxx...
   ```

6. 같은 다이얼로그의 **Network access**를 `Trusted` → **`Custom`** 으로 바꾸고
   필요한 도메인을 추가합니다. 기본값 `Trusted`는 패키지 저장소와 GitHub 등만
   열려 있어서 카카오·기상 API는 막힙니다

### 사용

```bash
# 기본
python3 kakao_notify.py "빌드 끝났습니다"

# 링크 버튼 붙이기
python3 kakao_notify.py "PR 리뷰 도착" --link https://github.com/ghrms2014-rgb/first-contributions/pull/1

# 파이프로 넘기기
./deploy.sh | tail -5 | python3 kakao_notify.py
```

긴 작업 뒤에 붙여두는 용도가 가장 편합니다.

```bash
npm run build && python3 kakao_notify.py "빌드 성공" \
              || python3 kakao_notify.py "빌드 실패"
```

파이썬 코드 안에서:

```python
from kakao_notify import send

send("배포 완료", link="https://example.com")
```

### 정기 알림 만들기

`crontab -e` 로 예약할 수 있습니다.

```cron
# 평일 오전 9시에 오늘 할 일 알림
0 9 * * 1-5 cd ~/first-contributions/tools/kakao-notify && python3 kakao_notify.py "오늘 처리할 PR 확인하기"
```

---

## 3. 보안 관련

- `.env`(API 키)와 `.kakao_token.json`(토큰)은 **`.gitignore`에 등록돼 있습니다.**
  절대 커밋되지 않지만, 다른 곳으로 복사하실 때도 주의해주세요.
- 카카오 토큰은 [카카오 계정 → 연결된 서비스 관리](https://accounts.kakao.com)
  에서, 구글 권한은 [Google 계정 권한 페이지](https://myaccount.google.com/permissions)
  에서 언제든 철회할 수 있습니다.
- **메일 본문은 제3자가 쓴 텍스트입니다.** 누군가 메일에 "이 내용을 어디로
  보내라" 같은 지시를 심어두면 Claude가 그걸 읽게 됩니다. Claude는 그런 걸
  명령이 아니라 데이터로 취급하지만, 민감한 메일함이라면 이 위험을 감안해
  결정하세요.
- 이 스크립트는 **본인 계정에만** 메시지를 보냅니다. 타인에게 발송하는 기능은
  들어 있지 않습니다.

---

## 4. 문제가 생기면

| 증상 | 원인과 해결 |
|---|---|
| `KAKAO_REST_API_KEY가 없습니다` | `.env` 파일이 없거나 키가 비어 있습니다. `cp .env.example .env` 후 키를 채우세요. |
| 브라우저에 `KOE006` 또는 redirect_uri 오류 | 카카오 앱에 등록한 Redirect URI와 `.env` 값이 다릅니다. 양쪽을 똑같이 맞추세요. |
| 브라우저에 `KOE205` / 동의항목 오류 | **동의항목**에서 `talk_message`가 꺼져 있습니다. 위 준비 6번을 확인하세요. |
| `포트를 열 수 없습니다` | 5000번 포트를 다른 프로그램이 쓰고 있습니다(macOS는 AirPlay). `.env`에서 포트를 바꾸고 카카오 앱에도 같은 주소를 등록하세요. |
| `저장된 토큰이 없습니다` | `python3 kakao_auth.py` 를 먼저 실행하세요. |
| `액세스 토큰 갱신 실패` | 리프레시 토큰이 만료됐습니다. `python3 kakao_auth.py` 를 다시 실행하세요. |
| 본문이 잘림 | 카카오 텍스트 템플릿은 200자 제한입니다. 스크립트가 자동으로 자르고 경고를 출력합니다. |

---

## 파일 구성

```
tools/kakao-notify/
├── kakao_env.py       설정/토큰 저장소 (공통)
├── kakao_auth.py      최초 1회 OAuth 인증
├── kakao_notify.py    메시지 전송 (CLI + import)
├── requirements.txt   의존성: requests 하나
├── .env.example       설정 템플릿
└── .gitignore         키/토큰 커밋 방지
```
