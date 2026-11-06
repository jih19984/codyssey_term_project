# AI Chatbot

FastAPI, Jinja2, SQLAlchemy와 PostgreSQL 기반으로 구현된 웹 대화형 AI 챗봇 서비스입니다.  
사용자의 이전 대화 문맥(최근 5개 Q/A)을 기억하여 자연스러운 대화를 제공하며, 모든 질문과 AI 답변을 데이터베이스에 안전하게 영속화하고 사용자별로 독립된 기록 조회를 지원합니다.

로컬 환경은 **Docker Compose**로 Web과 PostgreSQL을 구동하며, 운영 환경은 **Render Web Service** 및 **Render PostgreSQL**을 통해 자동 배포됩니다.

---

## 1. 프로젝트 개요 (Overview)

### 1.1 문제 정의
- 기존 단순 AI API 호출 도구는 이전 대화의 맥락이 단절되어 연속적인 질문과 심층적인 피드백을 주고받기 어렵습니다.
- 사용자별 질문과 AI 답변 내역이 보존되지 않아 이전에 조회한 유용한 답변을 다시 열람하거나 관리할 수 없는 문제가 있습니다.
- 멀티유저 웹 환경에서 사용자의 민감한 대화 내역이 다른 사용자에게 노출되지 않도록 하는 엄격한 소유권 격리와 웹 보안(세션 위변조 방지, CSRF 보호)이 필요합니다.

### 1.2 타깃 사용자
- 웹 브라우저를 통해 손쉽게 AI와 대화하고, 연속적인 질의응답을 통해 학습 또는 업무 보조를 받고자 하는 일반 사용자.
- 과거에 나눈 AI와의 대화 이력을 일자별·시간순으로 확인하고 관리하고자 하는 사용자.

### 1.3 핵심 사용자 시나리오
1. **회원가입**: 신규 사용자는 `/auth/signup`에서 정책(영숫자 3~20자 아이디, 영문 대문자·소문자·특수문자를 각각 1개 이상 포함한 8~100자 비밀번호)에 맞는 계정을 생성합니다. 비밀번호는 Argon2 안전 해시로 암호화되어 저장됩니다.
2. **로그인 및 세션 획득**: `/auth/login`에서 로그인에 성공하면 변조가 불가능한 서명된 HTTP-only 세션 쿠키(`session`)와 CSRF 토큰을 부여받고 홈 화면(`/`)으로 이동합니다.
3. **질문 전송**: 로그인 후 `/chat` 화면으로 이동하여 질문(1~2,000자)을 입력하고 전송합니다. 전송 중에는 중복 요청 방지를 위해 버튼이 비활성화됩니다.
4. **AI 응답 수신 및 저장**: 서버는 사용자의 최근 대화 이력 5건을 문맥으로 구성하여 AI 게이트웨이(Codyssey Neito)를 호출합니다. AI 답변이 도착하면 질문과 답변, 모델명, 지연 시간(ms)을 원자적(트랜잭션)으로 PostgreSQL에 기록한 뒤 화면에 실시간으로 표시합니다.
5. **대화 이력 조회**: 사용자는 상단 메뉴의 `/history` 페이지나 `GET /api/me/chats` API를 통해 본인이 나눈 과거 대화 목록을 최신순으로 페이징 조회할 수 있습니다. 타인의 대화는 엄격히 차단됩니다.

---

## 2. 시스템 아키텍처 및 계층별 책임

### 2.1 요청-응답 흐름 다이어그램

```mermaid
flowchart TD
    Browser["사용자 브라우저 (Jinja2 UI / Vanilla JS)"]
    
    subgraph WebServer ["FastAPI Application (app/)"]
        Middleware["SessionMiddleware & Request Logger (UUID request_id)"]
        Router["Routers (auth, chat, history)"]
        Service["Services (ChatService)"]
        Repo["Repositories (chat_repository)"]
        AIClient["Integrations (AnthropicGatewayClient)"]
    end
    
    Database[("PostgreSQL DB (Docker / Render)")]
    AIGateway["Codyssey AI Gateway (Neito / Claude)"]

    Browser -- "1. HTTP 요청 (Cookie: session, CSRF 토큰)" --> Middleware
    Middleware -- "2. request_id 발급 & 라우팅" --> Router
    Router -- "3. 입력 검증 (Pydantic / Policy)" --> Service
    Service -- "4. 최근 대화 문맥(5건) 조회" --> Repo
    Repo -- "5. SELECT recent messages" --> Database
    Service -- "6. Q/A 문맥 구성 및 질의" --> AIClient
    AIClient -- "7. HTTPS POST /v1/messages" --> AIGateway
    AIGateway -- "8. AI 텍스트 응답" --> AIClient
    Service -- "9. Q/A 및 메타데이터 원자적 저장" --> Repo
    Repo -- "10. INSERT conversation & messages (Commit)" --> Database
    Service -- "11. ChatResult 반환" --> Router
    Router -- "12. JSON / HTML 렌더링 응답" --> Browser
```

### 2.2 디렉토리 구조 및 컴포넌트 역할

```text
app/
├── main.py              # FastAPI 앱 생성, 세션/로깅 미들웨어 및 전역 예외 핸들러 등록
├── config.py            # Pydantic BaseSettings 기반 환경변수 검증 및 로드
├── db.py                # SQLAlchemy 엔진, SessionLocal 팩토리, get_db 의존성
├── access_control.py    # 서명 쿠키 세션 검증, get_current_user, CSRF 토큰 발급/검증
├── security.py          # Argon2 기반 비밀번호 해싱 및 검증
├── validation.py        # 아이디/비밀번호 길이 및 정규식 정책 정의
├── logging_utils.py     # 이벤트 기반 표준 구조화 로그 유틸리티
├── models/              # SQLAlchemy ORM 모델 정의 (User, Conversation, Message)
├── schemas/             # Pydantic 요청/응답 DTO 스키마 (ChatRequest, ChatResponse 등)
├── routers/             # HTTP 라우팅 및 컨트롤러 계층
│   ├── auth.py          # 회원가입(/auth/signup), 로그인(/auth/login), 로그아웃(/auth/logout)
│   ├── chat.py          # 챗봇 뷰(/chat), 질문 전송 API(/api/chat)
│   └── history.py       # 대화 기록 뷰(/history), 기록 목록 API(/api/me/chats)
├── services/            # 비즈니스 로직 계층
│   ├── auth_service.py  # 회원가입 정책 검증/등록, 자격증명 인증 및 비밀번호 검증
│   └── chat_service.py  # 문맥 조회, AI 호출, 지연시간 측정, 트랜잭션 저장 조율
├── repositories/        # 데이터베이스 접근 계층
│   ├── chat_repository.py # 대화/메시지 CRUD 및 철저한 user_id 소유권 격리 쿼리
│   └── user_repository.py # 사용자 단건 조회(ID/username) 및 신규 사용자 생성
├── integrations/        # 외부 서비스 연동 계층
│   └── ai_client.py     # AI 게이트웨이 연동 어댑터 (AnthropicGatewayClient, FakeAIClient)
├── templates/           # Jinja2 서버사이드 HTML 템플릿
└── static/              # CSS 스타일시트 및 Vanilla JavaScript 파일
```

---

## 3. API 및 라우트 명세 (API Specification)

### 3.1 라우트 엔드포인트 목록

| 메서드 | 경로 | 인증 여부 | CSRF 검증 | 설명 | 주요 HTTP 상태 코드 |
| :---: | :--- | :---: | :---: | :--- | :--- |
| `GET` | `/` | 선택 | - | 서비스 홈 화면 (로그인 상태에 따라 동적 UI) | `200` |
| `GET` | `/auth/signup` | 불필요 | - | 회원가입 입력 폼 화면 | `200` |
| `POST` | `/auth/signup` | 불필요 | 폼 필드 | 회원가입 처리 (아이디/비밀번호 정책 검증) | `303`(성공), `422`(형식오류), `409`(아이디중복), `403`(CSRF) |
| `GET` | `/auth/login` | 불필요 | - | 로그인 입력 폼 화면 | `200` |
| `POST` | `/auth/login` | 불필요 | 폼 필드 | 로그인 인증 및 세션 쿠키 발급 | `303`(성공), `401`(인증실패), `422`(형식오류), `403`(CSRF) |
| `POST` | `/auth/logout` | 필수 | 폼 필드 | 세션 쿠키 무효화 및 로그아웃 | `303`(성공), `403`(CSRF) |
| `GET` | `/chat` | 필수 | - | 웹 챗봇 대화 인터페이스 화면 | `200`, `303`(미인증 시 `/auth/login` 이동) |
| `POST` | `/api/chat` | 필수 | 헤더 | AI 질문 전송, 답변 수신 및 DB 자동 영속화 | `200`(성공), `401`(미인증), `403`(CSRF), `422`(길이위반), `500`, `502`, `504` |
| `GET` | `/history` | 필수 | - | 대화 이력 조회 웹 페이지 | `200`, `303`(미인증 시 `/auth/login` 이동) |
| `GET` | `/api/me/chats` | 필수 | - | 로그인 사용자 본인의 대화 기록 JSON API | `200`, `401`(미인증) |
| `GET` | `/health` | 불필요 | - | 외부 의존성 없는 프로세스 Liveness 상태 점검 | `200` (`{"status": "ok"}`) |
| `GET` | `/docs` | 불필요 | - | FastAPI 자동 생성 OpenAPI/Swagger 문서 | `200` |

### 3.2 인증 및 CSRF 보안 정책
- **서명된 세션 쿠키**: `starlette.middleware.sessions.SessionMiddleware`를 사용하여 쿠키(`session`)를 안전하게 서명합니다. 클라이언트 쿠키에는 오직 검증된 `user_id` 정수값만 포함되며, 서버는 매 요청마다 DB에서 사용자 실존 여부를 검증합니다.
- **CSRF 토큰**:
  - HTML Form 전송 시: `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` 필드로 전송되어 검증합니다.
  - JSON API(`POST /api/chat`) 호출 시: `chat.html`의 메타데이터에서 토큰을 추출하여 HTTP 요청 헤더 `X-CSRF-Token`에 실어 전송합니다.

### 3.3 핵심 API 명세 예시

#### [POST] `/api/chat` - 질문 전송 및 AI 응답

- **Headers**:
  ```http
  Content-Type: application/json
  X-CSRF-Token: <CSRF_TOKEN>
  Cookie: session=<SESSION_COOKIE>
  ```
- **Request Body**:
  ```json
  {
    "question": "FastAPI에서 세션은 어떻게 관리하나요?"
  }
  ```
- **Success Response (200 OK)**:
  ```json
  {
    "chat_id": 14,
    "answer": "FastAPI에서는 Starlette의 SessionMiddleware를 활용하여 클라이언트 쿠키에 서명된 형태로 세션 정보를 안전하게 저장할 수 있습니다...",
    "created_at": "2026-10-15T01:30:00Z",
    "request_id": "a1b2c3d4e5f6789012345678abcdef01"
  }
  ```
- **Error Responses**:
  - **422 Unprocessable Content** (질문 길이 위반: 1자 미만 공백이거나 2,000자 초과):
    ```json
    {
      "error": {
        "code": "VALIDATION_ERROR",
        "message": "질문은 공백을 제외하고 1~2000자 사이여야 합니다.",
        "request_id": "a1b2c3d4e5f6789012345678abcdef01"
      }
    }
    ```
  - **401 Unauthorized** (미로그인 상태 요청):
    ```json
    {
      "detail": "로그인이 필요합니다."
    }
    ```
  - **403 Forbidden** (CSRF 헤더 누락 또는 불일치):
    ```json
    {
      "detail": "유효하지 않은 CSRF 토큰입니다."
    }
    ```
  - **504 Gateway Timeout** (AI 호출 시간 초과):
    ```json
    {
      "error": {
        "code": "AI_TIMEOUT",
        "message": "응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
        "request_id": "a1b2c3d4e5f6789012345678abcdef01"
      }
    }
    ```
  - **502 Bad Gateway** (외부 AI 게이트웨이 장애):
    ```json
    {
      "error": {
        "code": "AI_UPSTREAM_ERROR",
        "message": "AI 서비스에 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        "request_id": "a1b2c3d4e5f6789012345678abcdef01"
      }
    }
    ```
  - **500 Internal Server Error** (DB 영속화 실패):
    ```json
    {
      "error": {
        "code": "DB_WRITE_ERROR",
        "message": "응답을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        "request_id": "a1b2c3d4e5f6789012345678abcdef01"
      }
    }
    ```

#### [GET] `/api/me/chats` - 본인 대화 기록 페이징 조회

- **Query Parameters**:
  - `limit` (int, 선택): 조회할 개수 (기본값: 20, 허용 범위: 1 ~ 100)
  - `offset` (int, 선택): 건너뛸 개수 (기본값: 0, 허용 범위: >= 0)
- **Headers**:
  ```http
  Cookie: session=<SESSION_COOKIE>
  ```
- **Success Response (200 OK)**:
  ```json
  {
    "items": [
      {
        "chat_id": 14,
        "question": "FastAPI에서 세션은 어떻게 관리하나요?",
        "answer": "FastAPI에서는 Starlette의 SessionMiddleware를 활용하여...",
        "created_at": "2026-10-15T01:30:00Z"
      },
      {
        "chat_id": 13,
        "question": "안녕하세요!",
        "answer": "안녕하세요! 무엇을 도와드릴까요?",
        "created_at": "2026-10-15T01:28:12Z"
      }
    ],
    "limit": 20,
    "offset": 0,
    "has_more": false
  }
  ```

---

## 4. 데이터베이스 구조 및 마이그레이션 (DB & Alembic)

### 4.1 ER 다이어그램 (ERD)

```mermaid
erDiagram
    users ||--o{ conversations : "user_id (1:N)"
    conversations ||--o{ messages : "conversation_id (1:N CASCADE)"

    users {
        int id PK "자동 증가 식별자"
        varchar20 username UK "로그인 아이디 (3~20자, 영숫자/-/_)"
        varchar255 password_hash "Argon2 비밀번호 해시"
        timestamptz created_at "계정 생성 시각 (UTC)"
    }
    conversations {
        int id PK "대화 세션 식별자"
        int user_id FK "users.id 외래키 (인덱스)"
        varchar200 title "대화 제목 (선택)"
        timestamptz created_at "생성 시각 (인덱스)"
    }
    messages {
        int id PK "메시지 식별자"
        int conversation_id FK "conversations.id 외래키 (CASCADE 삭제)"
        varchar20 role "메시지 역할 ('user' 또는 'assistant')"
        text content "질문 또는 답변 본문"
        timestamptz created_at "저장 시각 (인덱스)"
        varchar100 ai_model "AI 모델명 (assistant 메시지만)"
        int latency_ms "응답 지연시간 (ms, assistant 메시지만)"
    }
```

### 4.2 테이블 상세 명세

**1) `users` (사용자 계정)**
- `id` (INTEGER, PK): 고유 사용자 식별자.
- `username` (VARCHAR(20), NOT NULL, UNIQUE INDEX): 영문/숫자/`_`/`-`로 구성된 3~20자 아이디.
- `password_hash` (VARCHAR(255), NOT NULL): Argon2 단방향 암호화 해시 문자열 (평문 절대 저장 금지).
- `created_at` (TIMESTAMPTZ, NOT NULL): 생성 시각.

**2) `conversations` (대화 세션)**
- `id` (INTEGER, PK): 대화 고유 번호.
- `user_id` (INTEGER, NOT NULL, FK → `users.id`): 소유자 식별자 (INDEX 적용으로 사용자별 고속 필터링).
- `title` (VARCHAR(200), NULL): 대화방 타이틀.
- `created_at` (TIMESTAMPTZ, NOT NULL, INDEX): 대화 생성 시각 (최신순 정렬용 인덱스).

**3) `messages` (대화 메시지 로그)**
- `id` (INTEGER, PK): 메시지 식별자.
- `conversation_id` (INTEGER, NOT NULL, FK → `conversations.id` ON DELETE CASCADE): 대화방 삭제 시 메시지도 연쇄 삭제.
- `role` (VARCHAR(20), NOT NULL, CHECK: `'user'`, `'assistant'`): 발화자 구분.
- `content` (TEXT, NOT NULL): 메시지 텍스트.
- `created_at` (TIMESTAMPTZ, NOT NULL, INDEX): 메시지 타임스탬프.
- `ai_model` (VARCHAR(100), NULL): 답변 생성에 사용된 모델명 (예: `claude-haiku-4`).
- `latency_ms` (INTEGER, NULL): API 응답 왕복 지연 시간 (밀리초).

### 4.3 Alembic Revision 관리 이력

빈 데이터베이스에서 `alembic upgrade head` 실행 시 아래 순서로 무결성을 유지하며 적용됩니다.

| 순서 | Revision ID | 주요 작업 내용 | 롤백(downgrade) 동작 |
| :---: | :--- | :--- | :--- |
| 1 | `f10750ed7e50` | `users` 테이블 생성 및 `ix_users_username` 유니크 인덱스 생성 | `users` 인덱스 및 테이블 삭제 |
| 2 | `20261005_0002` | `conversations` 테이블 및 `user_id`, `created_at` 인덱스 생성 | `conversations` 인덱스 및 테이블 삭제 |
| 3 | `20261005_0003` | `messages` 테이블 생성, `ck_messages_role` CHECK 제약, `ON DELETE CASCADE` 외래키 생성 | `messages` 인덱스 및 테이블 삭제 |
| 4 | `20261011_0004` | `users.username` 컬럼 길이를 50자에서 20자로 축소 (정책 통일, 이슈 #14) | 컬럼 길이를 다시 50자로 확장 |

> [!NOTE]
> `20261011_0004` 적용 시 기존 DB에 21자 이상의 username이 존재하면 PostgreSQL 오류가 발생합니다. 운영 DB 적용 전 다음 쿼리로 검증을 권장합니다:
> ```sql
> SELECT id, username, length(username) FROM users WHERE length(username) > 20;
> ```

### 4.4 마이그레이션 CLI 명령어

```bash
# 최신 마이그레이션 적용
docker compose exec web alembic upgrade head

# 1단계 롤백 (로컬 개발 환경 전용)
docker compose exec web alembic downgrade -1

# 현재 DB 리비전 확인
docker compose exec web alembic current

# 코드베이스 최신 헤드 리비전 확인
docker compose exec web alembic heads

# 전체 리비전 히스토리 확인
docker compose exec web alembic history
```

### 4.5 데이터베이스 저장 결과 직접 확인 절차

평가자 또는 개발자가 로컬 PostgreSQL 컨테이너에 직접 접속하여 저장 결과를 검증할 수 있는 읽기 전용 쿼리입니다.

```bash
# 로컬 PostgreSQL psql CLI 접속
docker compose exec postgres psql -U chatbot -d chatbot
```

```sql
-- 1. 적용된 Alembic 마이그레이션 리비전 확인
SELECT version_num FROM alembic_version;

-- 2. 전체 테이블 목록 및 스키마 확인
\dt
\d users
\d conversations
\d messages

-- 3. 가입된 사용자 계정 확인 (비밀번호 해시 제외 안전 조회)
SELECT id, username, created_at FROM users ORDER BY id ASC;

-- 4. 사용자별 대화 세션 및 누적 메시지 건수 집계
SELECT 
    u.id AS user_id, 
    u.username, 
    count(DISTINCT c.id) AS total_conversations, 
    count(m.id) AS total_messages
FROM users u
LEFT JOIN conversations c ON c.user_id = u.id
LEFT JOIN messages m ON m.conversation_id = c.id
GROUP BY u.id, u.username
ORDER BY u.id ASC;

-- 5. 최근 10건의 질문 및 AI 응답 상세 로그 (질문, 모델, 지연시간, 일시)
SELECT 
    m.id AS message_id,
    c.id AS conversation_id,
    u.username,
    m.role,
    left(m.content, 50) AS preview_content,
    m.ai_model,
    m.latency_ms,
    m.created_at
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
JOIN users u ON u.id = c.user_id
ORDER BY m.created_at DESC, m.id DESC
LIMIT 10;
```

운영 환경(Render PostgreSQL)에서도 Render 대시보드의 **External Database URL**을 이용해 동일한 쿼리를 안전하게 수행할 수 있습니다.

---

## 5. 환경 변수 설정 (Configuration)

`.env` 파일은 민감한 정보를 포함하므로 Git 버전 관리에서 제외되며, 템플릿 파일인 [`.env.example`](.env.example)을 복사하여 구성합니다.

| 환경 변수명 | 필수 여부 | 기본값 (개발용) | 설명 |
| :--- | :---: | :--- | :--- |
| `APP_ENV` | 선택 | `development` | 실행 환경 (`development`, `test`, `production`). `production`일 경우 쿠키에 `Secure` 플래그 강제 적용 |
| `DATABASE_URL` | 선택 | `postgresql://chatbot:chatbot@postgres:5432/chatbot` | PostgreSQL 접속 URL. Render에서는 서비스 내부 Internal Database URL 지정 |
| `SESSION_SECRET` | **필수** | (최소 32자 임의 문자열) | 세션 쿠키 위변조 방지를 위한 암호화 서명 비밀키. 운영 환경에서는 무작위 비밀값 사용 |
| `AI_API_KEY` | **필수** | (공란) | Codyssey Neito 게이트웨이 인증용 API 키. 미지정 시 앱 기동 단계에서 검증 실패 |
| `AI_BASE_URL` | 선택 | `https://copa.codyssey.kr` | AI 게이트웨이 호스트 주소 |
| `AI_MODEL` | 선택 | `claude-haiku-4` | 사용할 기본 AI 모델 식별자 |
| `AI_TIMEOUT_SECONDS` | 선택 | `10.0` | AI 게이트웨이 호출 시 타임아웃 제한 시간(초) |

---

## 6. 로컬 개발 환경 실행 (Getting Started)

### 개발용 ASGI 이벤트 로그

`APP_ENV=development`이면 `create_app()`이 `ASGILoggingMiddleware`를 등록합니다.
`production`과 그 외 값에서는 ASGI 상세 로그가 비활성화됩니다. 기존 요청·AI 호출·DB
저장 로그는 환경에 관계없이 유지됩니다. 배포 환경 이름은 `product`가 아닌
`production`입니다. 환경값을 변경한 뒤에는 서버를 다시 시작해야 합니다.

```bash
APP_ENV=development uvicorn app.main:create_app --factory --reload
```

메서드·경로와 ASGI 이벤트 종류, 본문 바이트 수, 응답 상태 및 처리 시간이 `app.events`
로거에 출력됩니다. `asgi_scope`에는 연결 유형(`type`), HTTP 버전(`http_version`),
스킴(`scheme`), 클라이언트·서버 주소(`client`, `server`)와 허용된 요청 헤더
(`content-type`, `content-length`, `accept`)만 기록합니다. 주소는 JSON 배열로,
헤더는 중복을 보존하는 이름·값 쌍의 JSON 배열로 표시합니다. 없는 주소는 `null`입니다.
쿠키·인증 헤더·쿼리 문자열·본문 원문은 출력하지 않습니다.
기존 업무 로그와 같은 `request_id`로 연결할 수 있습니다. 아래는 축약한 예시입니다.

```text
asgi_request_start request_id=abc method=POST path=/api/chat
asgi_scope request_id=abc type=http http_version=1.1 scheme=http client=["192.168.65.1", 52312] server=["172.18.0.2", 8000] headers=[["content-type", "application/json"], ["content-length", "32"]]
request_received request_id=abc method=POST path=/api/chat
asgi_receive request_id=abc type=http.request body_bytes=32 more_body=False
...
asgi_send request_id=abc type=http.response.start status=200
asgi_send request_id=abc type=http.response.body body_bytes=180 more_body=True
asgi_send request_id=abc type=http.response.body body_bytes=0 more_body=False
asgi_request_end request_id=abc duration_ms=125.0 response_complete=True
```

청크 수와 이벤트 순서는 요청 처리 방식에 따라 달라집니다. 본문을 읽지 않는 요청에서는
`asgi_receive`가 없을 수 있으며, 로깅을 위해 본문을 추가로 읽지는 않습니다.
`send` 로그는 다음 계층으로 이벤트 전달이 성공했다는 뜻이고, 브라우저 수신이나 UI 반영
완료를 뜻하지 않습니다. `response_complete`는 마지막 HTTP 응답 본문 이벤트의 전달 여부입니다.

이 미들웨어는 기존 HTTP·세션 미들웨어 바깥, Starlette의 `ServerErrorMiddleware` 안쪽에
위치합니다. 처리되지 않은 예외는 `asgi_request_error`에 예외 타입을 기록하고 그대로
전파합니다. 이 경우 최외곽 오류 처리기가 생성한 500 응답은 ASGI 상세 로그의 관찰 범위
밖이며, 기존 `unhandled_error` 로그에서 확인합니다. HTTP 외 lifespan/WebSocket은 그대로
통과시킵니다. 로그를 영구 저장하는 기능은 포함하지 않습니다.

DB 연결 없이 관련 테스트를 실행할 수 있습니다.

```bash
python -m pytest tests/test_asgi_logging.py -q
```

### 6.1 요구 사항
- Docker 24.0+ 및 Docker Compose v2+
- Git

### 6.2 실행 단계
1. **저장소 복제 및 디렉토리 이동**:
   ```bash
   git clone https://github.com/CodysseyBMB/codyssey_term_project.git
   cd codyssey_term_project
   ```

2. **환경 변수 파일 생성**:
   ```bash
   cp .env.example .env
   # .env 파일을 열어 AI_API_KEY 및 SESSION_SECRET 값을 입력합니다.
   ```

3. **컨테이너 빌드 및 실행**:
   ```bash
   docker compose up --build
   ```
   PostgreSQL이 준비(Healthy) 상태가 되면 `compose.yaml`의 커맨드에 따라 `alembic upgrade head`가 자동 실행되어 최신 스키마가 적용되고 FastAPI Uvicorn 서버가 포트 8000에서 시작됩니다.

4. **웹 브라우저 접속**:
   - 대시보드 홈: <http://localhost:8000/>
   - 챗봇 화면: <http://localhost:8000/chat>
   - 대화 기록 화면: <http://localhost:8000/history>
   - Swagger API 문서: <http://localhost:8000/docs>
   - Health Check: <http://localhost:8000/health>

5. **백그라운드 실행 및 종료**:
   ```bash
   # 백그라운드 구동
   docker compose up -d

   # 서비스 종료
   docker compose down

   # DB 데이터 볼륨까지 완전 초기화할 때만 사용:
   docker compose down -v
   ```

---

## 7. 코드 품질 검사 및 테스트 (Quality & Testing)

컨테이너 환경에서 린터와 자동화 테스트 스위트를 구동합니다.

```bash
# 컨테이너가 실행 중인 경우
docker compose exec web ruff check .
docker compose exec web pytest

# 1회성(일회용) 컨테이너로 검사만 수행할 경우
docker compose run --rm web ruff check .
docker compose run --rm web pytest
```

### CI 자동 검증 (GitHub Actions)
`.github/workflows/pr-check.yml` 워크플로는 `main` 브랜치를 향한 모든 Pull Request에 대해 다음 검증을 자동으로 수행합니다:
1. Ubuntu 환경에서 Python 3.12 설정 및 의존성 설치
2. 격리된 PostgreSQL 서비스 컨테이너(`postgres:17-alpine`) 기동
3. `ruff check .`를 통한 Python 코드 스타일 및 린트 검사
4. `alembic upgrade head`를 격리된 DB에 적용하여 마이그레이션 정상 동작 여부 확인
5. `pytest`를 통한 모델, 인증, 세션, CSRF, AI 어댑터, 마이그레이션 멱등성 및 롤백 테스트 자동 수행

---

## 8. 클라우드 배포 (Render Deployment)

운영 환경은 **Render Free Web Service** 및 **Render PostgreSQL**에 무중단 자동 배포되도록 구성되어 있습니다. (확인 기준일: 2026-10-15)

### 8.1 배포 설정 규격
- **환경**: Python 3.12
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT`
- **Health Check Path**: `/health`
- **환경 변수**:
  - `APP_ENV`: `production`
  - `DATABASE_URL`: Render PostgreSQL의 **Internal Database URL** 등록
  - `SESSION_SECRET`: 32자 이상의 안전한 프로덕션 비밀키 등록
  - `AI_API_KEY`: 운영용 Codyssey Neito API Key 등록

> [!WARNING]
> Render의 Free PostgreSQL 인스턴스는 생성 후 **30일** 뒤 자동 만료(삭제)됩니다. 최종 프로젝트 평가 및 시연 일정을 고려하여 DB 만료일을 사전에 점검하고 필요 시 백업을 수행해야 합니다.

---

## 9. 팀 구성 및 역할별 기여 내역 (Team & Contributions)

본 프로젝트는 3인의 팀원이 GitHub Flow 전략에 따라 이슈 발급 → 기능 브랜치 개발 → PR 코드 리뷰 및 승인(Approval) → CI 통과 후 병합을 거쳐 완성되었습니다.

| 성명 | GitHub 계정 | 주요 담당 역할 | 세부 구현 내용 및 기여 작업 | 관련 PR |
| :---: | :---: | :---: | :--- | :---: |
| **배재민**<br>(팀장) | `mulloc1` | **백엔드 / 인증·세션·문맥** | • Starlette 서명 쿠키 기반 세션 로그인/로그아웃 구현 및 보안 쿠키 설정<br>• 인증 접근 제어 미들웨어(`require_user`) 및 CSRF 방어 로직 구현<br>• AI 최근 문맥(5개 Q/A) 취합 알고리즘 및 대화/메시지 동시 저장 조율<br>• 사용자별 대화 이력 페이징 API(`GET /api/me/chats`) 및 `/history` 화면 구현<br>• 인증 비즈니스 로직의 서비스·저장소 계층 분리 리팩토링 | PR #15<br>PR #18<br>PR #20<br>PR #24 |
| **정인호** | `jih19984`<br>(`Ino`) | **백엔드 / API·통합·AI 연동** | • 회원가입 라우터 구현 및 Argon2 비밀번호 단방향 해싱 적용<br>• AI 게이트웨이(Codyssey Neito / Claude) 연동 클라이언트 및 어댑터 패턴 구축<br>• 챗봇 실시간 대화 화면(`/chat`) 및 `POST /api/chat` 엔드포인트 구현<br>• 회원 아이디(3~20자) 및 비밀번호(8~100자) 유효성 검증 정책 모듈 통일<br>• 요청/AI/DB 생명주기 구조화 이벤트 로깅 및 통합 테스트/CI 파이프라인 구축 | PR #13<br>PR #17<br>PR #19<br>PR #21<br>PR #22 |
| **조은익** | `nick19850906-debug`<br>(`lucid`) | **DB / 모델·마이그레이션** | • SQLAlchemy `Conversation`, `Message` ORM 모델 및 1:N CASCADE 관계 설계<br>• Alembic 마이그레이션(conversations, messages 테이블, 복합 인덱스, CHECK 제약) 구현<br>• 엄격한 `user_id` 기반 소유권 검증 및 격리된 대화·메시지 DB 접근 쿼리 작성<br>• 모델 영속화, 외래키 무결성, 마이그레이션 멱등성 및 롤백 검증 테스트 작성<br>• 공식 평가 체크리스트 1~6번 충족을 위한 README 문서 총괄 보강 및 명세화 | PR #16<br>PR #25<br>(본 PR) |

---

## 10. 관련 문서 (Documents)

- [전체 구현 계획서 (plan.md)](docs/plan.md): 프로젝트 요구사항 분석, 설계 원칙, P0/P1 완료 기준 및 아키텍처 가이드
- [기여 및 협업 가이드 (CONTRIBUTING.md)](docs/CONTRIBUTING.md): GitHub Flow 브랜치 전략, 커밋 컨벤션, PR 규칙 및 로컬 검증 지침
