# 테스트 안내

이 폴더의 테스트가 각각 무엇을 검증하는지 정리한 문서다.

## 실행 방법

테스트는 실제 PostgreSQL에 연결해서 실행한다. `DATABASE_URL`이 가리키는 DB에 Alembic으로 스키마를 만들고, 테스트마다 테이블을 비운다.

```bash
docker compose exec web pytest -q
```

> 주의: 테스트는 시작할 때마다 `users` 테이블을 `TRUNCATE ... CASCADE`로 비운다. `docker compose exec web`은 개발용 DB(`chatbot`)를 그대로 쓰기 때문에, 브라우저에서 만든 계정과 대화도 함께 지워진다. 개발 데이터를 지키려면 테스트 전용 DB를 따로 지정해서 실행한다.
>
> ```bash
> docker compose exec postgres createdb -U chatbot chatbot_test   # 처음 한 번만
> docker compose exec -e DATABASE_URL=postgresql://chatbot:chatbot@postgres:5432/chatbot_test web pytest -q
> ```

CI(`.github/workflows/pr-check.yml`)는 PR마다 Postgres 서비스를 띄우고 `ruff`, `alembic upgrade head`, `pytest`를 차례로 실행한다.

## 공통 준비물

| 파일 | 역할 |
|---|---|
| `conftest.py` | pytest fixture 모음. 각 fixture가 하는 일은 아래 목록에 정리했다. |
| `fakes.py` | `FakeAIClient`: 실제 네트워크 없이 정해 둔 답변이나 예외를 돌려주는 가짜 AI 클라이언트. 넘겨받은 `messages`를 `received_messages`에 저장한다. |
| `helpers.py` | `get_csrf_token`: 폼 hidden input에서 CSRF 토큰을 꺼낸다. `get_header_csrf_token`: `<body data-csrf-token>` 속성에서 CSRF 토큰을 꺼낸다. |

`conftest.py`의 fixture는 다음과 같다.

- `database_url`: 환경 변수 `DATABASE_URL`을 읽는다.
- `migrated_database_url`: `alembic upgrade head`로 테이블을 만든다.
- `_reset_tables`: 자동으로 실행되며, 테스트마다 테이블을 비운다(`TRUNCATE`).
- `settings`: 테스트용 설정을 만든다.
- `client`: 실제 앱에 요청을 보내는 `TestClient`를 만든다.
- `db_session`: 저장 결과를 직접 확인하는 검증용 DB 세션을 연다.

AI는 두 가지 방법으로 가짜로 바꾼다.

- **라우터·서비스 테스트:** `client.app.state.ai_client = FakeAIClient(...)`
- **AI 클라이언트 자체 테스트:** `httpx.MockTransport`로 네트워크만 가짜로 바꾸고, 실제 HTTP 처리 코드는 그대로 실행한다.

---

## 파일별 설명

### `test_ai_client.py`: AI 게이트웨이 클라이언트
| 테스트 | 검증 내용 |
|---|---|
| `test_generate_returns_text_on_success` | 정상 응답에서 `content[0].text`를 꺼내고, 요청 헤더(`x-api-key`, `anthropic-version`)와 본문이 올바른지 |
| `test_generate_raises_timeout_error` | 시간 초과가 `AITimeoutError`로 바뀌는지 |
| `test_generate_raises_provider_error_on_failure_status` | 4xx/5xx 응답이 `AIProviderError`로 바뀌는지 |
| `test_generate_raises_connection_error` | 연결 실패가 `AIConnectionError`로 바뀌는지 |
| `test_generate_rejects_invalid_success_payload` | 200이어도 응답 형식이 잘못되면 `AIProviderError`가 나는지 |
| `test_repr_does_not_leak_api_key` | 객체를 출력해도 API 키가 드러나지 않는지 |
| `test_fake_client_*` | 가짜 클라이언트가 정해 둔 답변과 예외를 돌려주는지 |
| `test_real_and_fake_clients_are_interchangeable` | 실제 클라이언트와 가짜 클라이언트가 같은 인터페이스(`generate`)를 갖는지 |

### `test_chat.py`: 채팅 화면과 `POST /api/chat`
| 테스트 | 검증 내용 |
|---|---|
| `test_chat_page_redirects_anonymous_user_to_login` | 로그인하지 않으면 `/chat`에서 로그인 화면으로 303 이동 |
| `test_chat_page_renders_for_authenticated_user` | 로그인하면 채팅 화면과 CSRF 토큰이 보임 |
| `test_api_chat_requires_authentication` | 로그인하지 않으면 401 |
| `test_api_chat_requires_csrf_header` | `X-CSRF-Token` 헤더가 없으면 403 |
| `test_api_chat_rejects_blank_question` | 공백만 있는 질문은 422 `VALIDATION_ERROR` |
| `test_api_chat_rejects_question_over_length_limit` | 2000자를 넘는 질문은 422 |
| `test_api_chat_returns_and_saves_ai_answer` | 200 응답과 답변 반환, 대화 1개와 메시지 2개 저장 |
| `test_api_chat_maps_ai_errors` | AI 시간 초과는 504 `AI_TIMEOUT`, 공급자 오류는 502 `AI_UPSTREAM_ERROR`. DB에는 아무것도 저장되지 않음 |
| `test_api_chat_maps_database_error` | 저장 실패는 500 `DB_WRITE_ERROR` |

### `test_chat_service.py`: 채팅 서비스 로직
| 테스트 | 검증 내용 |
|---|---|
| `test_ask_sends_only_current_question_without_history` | 이전 대화가 없으면 현재 질문만 AI에 보냄 |
| `test_ask_sends_latest_five_pairs_oldest_first_and_excludes_other_user` | 최근 5개 질문·답변을 오래된 순으로 보내고, 다른 사용자의 대화는 제외 |
| `test_ask_saves_question_and_answer_in_one_new_conversation` | 질문과 답변을 새 대화 하나에 함께 저장 |
| `test_ai_failure_does_not_save_partial_conversation` | AI 호출이 실패하면 아무것도 저장하지 않음 |
| `test_second_message_failure_rolls_back_entire_conversation` | 답변 저장이 실패하면 대화 전체를 롤백 |

### `test_signup.py`: 회원가입
| 테스트 | 검증 내용 |
|---|---|
| `test_signup_success_hashes_password` | 가입하면 303 이동, 비밀번호는 평문이 아니라 해시로 저장 |
| `test_signup_rejects_duplicate_username` | 이미 있는 아이디는 409 |
| `test_signup_rejects_short_password` / `..._over_max_length` | 비밀번호가 8~100자를 벗어나면 422 |
| `test_signup_rejects_password_missing_required_characters` | 대문자, 소문자, 특수문자 중 하나라도 빠지면 422 |
| `test_signup_accepts_password_with_required_characters` | 조건을 모두 갖춘 비밀번호는 가입 성공 |
| `test_signup_rejects_username_outside_length_range` / `..._accepts_username_at_length_boundary` | 아이디 길이 경계값: 2자와 21자는 거부, 3자와 20자는 통과 |
| `test_signup_rejects_username_with_disallowed_characters` | 공백, 특수문자, 한글, 이모지가 들어간 아이디는 거부 |
| `test_signup_does_not_sanitize_password_before_hashing` | 비밀번호를 strip하지 않고 원문 그대로 해시 |

### `test_auth_service.py`: 인증 서비스 (로그인·회원가입 공통 규칙)
| 테스트 | 검증 내용 |
|---|---|
| `test_normalize_and_validate_credentials_trims_only_username` | 아이디만 공백 제거하고 비밀번호는 그대로 둠 |
| `test_login_and_signup_share_credential_format_validation` | 로그인과 회원가입이 같은 형식 검증을 씀 |
| `test_credential_validation_uses_specific_policy_message` | 아이디 오류와 비밀번호 오류의 안내 메시지가 구분됨 |
| `test_register_normalizes_username_and_hashes_password` | 가입할 때 아이디 정규화와 비밀번호 해시 |
| `test_authenticate_returns_matching_user` | 올바른 정보로 로그인하면 해당 사용자를 반환 |
| `test_authenticate_rejects_unknown_user_and_wrong_password` | 없는 아이디나 틀린 비밀번호는 같은 예외 |
| `test_register_rolls_back_duplicate_username` | 중복 가입은 롤백되고, 그 뒤 다른 가입은 정상 진행 |
| `test_register_rejects_password_without_required_characters` | 조합 규칙에 맞지 않는 비밀번호는 가입 거부 |
| `test_authenticate_allows_legacy_password_without_required_characters` | 정책이 바뀌기 전에 가입한 사용자도 기존 비밀번호로 로그인 가능 |

### `test_auth.py`: 로그인과 로그아웃
| 테스트 | 검증 내용 |
|---|---|
| `test_login_success_sets_minimal_session_cookie` | 로그인하면 세션 쿠키에 최소한의 정보(`user_id`)만 저장 |
| `test_login_trims_username` | 아이디 앞뒤 공백을 제거하고 로그인 |
| `test_login_uses_same_error_for_unknown_user_and_wrong_password` | 아이디가 없을 때와 비밀번호가 틀릴 때 같은 메시지를 보여 줘서 계정 존재 여부를 숨김 |
| `test_login_rejects_*` | 형식 오류(길이, 허용 문자)는 422 |
| `test_index_switches_actions_after_login` | 로그인 전후로 홈 화면 메뉴가 바뀜 |
| `test_logout_clears_session_and_is_idempotent` | 로그아웃하면 세션이 지워지고, 여러 번 해도 안전 |
| `test_production_cookie_is_secure` | 운영 환경에서는 쿠키에 `Secure` 속성 |
| `test_tampered_cookie_is_ignored_on_logout` | 변조된 쿠키는 무시 |

### `test_access_control.py`: 접근 제어와 CSRF
| 테스트 | 검증 내용 |
|---|---|
| `test_anonymous_page_redirects_to_login` / `test_anonymous_api_returns_401` | 로그인하지 않았을 때 화면은 303 이동, API는 401 |
| `test_authenticated_identity_cannot_be_overridden` | 요청 값으로 다른 사용자인 척할 수 없음 |
| `test_deleted_user_session_is_rejected_and_cleared` | 삭제된 사용자의 세션은 거부하고 지움 |
| `test_invalid_user_id_type_is_rejected_and_session_is_cleared` | 세션의 `user_id` 타입이 잘못되면 거부 |
| `test_other_users_conversation_is_hidden` | 다른 사용자의 대화는 보이지 않음 |
| `test_auth_forms_render_csrf_token` / `test_logout_form_renders_csrf_token` | 폼에 CSRF 토큰이 들어 있음 |
| `test_public_form_post_without_csrf_is_rejected` / `test_invalid_form_csrf_is_rejected` | 폼 CSRF 토큰이 없거나 틀리면 403 |
| `test_csrf_token_from_another_client_is_rejected` | 다른 브라우저(세션)의 토큰은 거부 |
| `test_logout_without_csrf_is_rejected` | CSRF 토큰 없는 로그아웃은 거부 |
| `test_api_header_csrf_is_required` | API는 `X-CSRF-Token` 헤더가 필수 |
| `test_login_rotates_csrf_token` | 로그인하면 CSRF 토큰을 새로 발급 |

### `test_history.py`: 대화 기록
| 테스트 | 검증 내용 |
|---|---|
| `test_history_page_redirects_anonymous_user_to_login` / `test_history_api_requires_authentication` | 로그인 필요 |
| `test_history_api_returns_only_current_users_chats_newest_first` | 내 대화만 최신순으로 반환 |
| `test_history_api_paginates_and_reports_has_more` | 페이지 나누기와 다음 페이지 존재 여부(`has_more`) |
| `test_history_api_rejects_invalid_pagination` | 잘못된 페이지 값은 거부 |
| `test_history_page_shows_empty_state_and_navigation` | 기록이 없을 때 안내 문구와 메뉴 표시 |
| `test_history_page_escapes_user_content_and_renders_local_time_hook` | 사용자 입력은 HTML 이스케이프해서 XSS 방지 |
| `test_history_page_renders_previous_and_next_links` | 이전·다음 링크 |
| `test_home_and_chat_pages_link_to_history` | 홈과 채팅 화면에 기록 링크가 있음 |

### `test_logging.py`: 이벤트 로그
| 테스트 | 검증 내용 |
|---|---|
| `test_get_request_logs_request_received` | 요청마다 `request_received` 로그 |
| `test_successful_chat_logs_ai_and_db_events_without_leaking_content` | 성공하면 `ai_call_start`, `ai_call_success`, `db_save_success` 로그. 비밀번호, 쿠키, API 키, 질문과 답변 원문은 로그에 없음 |
| `test_ai_failure_logs_ai_call_failure` | AI 실패 시 `ai_call_failure` 로그 |
| `test_persistence_failure_logs_db_save_failure` | 저장 실패 시 `db_save_failure` 로그 |
| `test_unexpected_error_returns_generic_response_and_logs_stack_trace` | 예상하지 못한 오류는 500 `INTERNAL_ERROR`로 응답하고 스택 트레이스를 로그에 남김 |

### `test_asgi_logging.py`: 개발용 ASGI 로깅 미들웨어
| 테스트 | 검증 내용 |
|---|---|
| `test_environment_and_shared_request_id` | 개발 환경에서만 붙고, 안쪽 로그와 같은 request_id를 씀 |
| `test_chunked_messages_are_forwarded_unchanged` | 나눠서 오는 응답을 바꾸지 않고 그대로 전달 |
| `test_scope_metadata_and_header_allowlist` | 허용된 헤더만 기록 (쿠키 등은 제외) |
| `test_non_http_is_passed_through` | HTTP가 아닌 요청은 그대로 통과 |
| `test_send_failure_is_propagated_without_marking_complete` | 응답 전송 실패를 숨기지 않고 그대로 전달 |

### `test_integration_flow.py`: 사용자 흐름 전체
| 테스트 | 검증 내용 |
|---|---|
| `test_signup_login_ask_and_see_answer_and_history` | 회원가입, 로그인, 질문, 답변 확인, 기록 화면까지 한 번에 |
| `test_ai_failure_returns_consistent_error_and_leaves_no_partial_history` | AI가 실패하면 공통 오류 형식으로 응답하고 기록에 아무것도 남지 않음 |

### `test_chat_repository.py`: 대화·메시지 저장소
대화와 메시지를 만들고 조회하는 기능을 검증한다. 모든 조회는 **소유자 기준**으로 제한된다(다른 사용자의 대화와 메시지는 보이지 않거나 추가되지 않음). 그 밖에 최신순 정렬과 limit/offset, 메시지 입력 순서, 최근 대화를 시간순으로 조회하는 기능(`list_recent_messages`)을 확인한다.

### `test_user_repository.py`: 사용자 저장소
사용자 생성과 아이디로 조회하기, 없는 아이디는 `None`, 전달받은 해시를 그대로 저장하는지 확인한다.

### `test_models.py`: DB 모델과 제약 조건
기본값(생성 시각 등), assistant 메시지의 추적 필드(`ai_model`, `latency_ms`)를 확인한다. 제약 조건으로는 `role`은 user와 assistant만 허용, 존재하지 않는 사용자 FK 거부, `content` 필수, 대화를 삭제하면 메시지도 함께 삭제되는지(CASCADE)를 확인한다.

### `test_alembic.py`: 마이그레이션
`upgrade head`를 여러 번 실행해도 안전한지, downgrade 후 다시 upgrade할 수 있는지 확인한다.

### `test_config.py`: 설정
`AI_API_KEY`가 없으면 앱이 시작 단계에서 명확한 오류로 실패하는지 확인한다.

### `test_health.py`: 기본 동작
홈 화면이 렌더링되는지, `/health`가 DB 없이도 응답하는지 확인한다.
