# 작업자 · 이력 관리

이 문서는 웹 콘솔의 **누가** 설정·기동·적용을 했는지 남기고, 관리자가 **작업자를 등록·정지**할 수 있게 한다. Earthworm 모듈 로그(`*_YYYYMMDD.log`)와 다르다. 모듈 로그는 프로세스가 쓴 파일이고, **작업 이력**은 웹이 기록하는 감사 로그다.

지금 코드는 공유 `EW_WEB_API_KEY` 하나다. 키가 같으면 작업자를 구분할 수 없다. 이력 관리가 성립하려면 **로그인 신원**이 모든 변경 API에 붙어야 한다.

[역할](diagrams/operator-roles.html)

[이력 흐름](diagrams/audit-flow.html)

MVP 위치: [plan_mvp.md](plan_mvp.md) **단계 2b**. 구성 보드 적용(4단계)보다 **먼저** 머지한다. 적용 이벤트에 작업자가 비어 있으면 이력이 아니다.

---

## 41. 목표

운영 책임자가 브라우저에서 다음을 한다.

1. **작업자**를 등록한다 (로그인 ID, 표시 이름, 역할, 사용/정지).
2. 본인 비밀번호로 로그인한다. 화면 헤더에 표시 이름이 보인다.
3. 역할에 따라 구성 보드·기동·파일·작업자 메뉴가 열리거나 막힌다.
4. **이력**에서 시각·작업자·동작·대상·결과(성공/실패)를 필터해 본다.
5. 이력 한 줄에서 그때의 백업 스냅샷(있으면)으로 간다. 이력 줄 자체는 고치거나 지우지 못한다.

하지 않는 것: LDAP/SSO(이후), Earthworm 리눅스 계정과 웹 작업자 동기화, 이력으로 `pau`를 자동 되돌리기.

---

## 42. 작업자 모델

저장소: `backend/data/control.sqlite` (SQLite). `app.json`에 사용자를 넣지 않는다. 이력이 늘어나도 JSON 전체를 다시 쓰지 않기 위함이다. EW 메타(`setup_complete`, clones)는 기존 `app.json`을 유지한다.

### 42.1 필드

| 컬럼 | 규칙 |
|------|------|
| `id` | 정수 PK |
| `username` | 로그인 ID. `[A-Za-z][A-Za-z0-9_.-]{2,31}`, 대소문자 무시 유일 |
| `display_name` | 화면용. 한글 가능. 이력에 이 이름을 남긴다(당시 값 스냅샷) |
| `password_hash` | argon2id. 평문·해시 모두 이력에 안 남김 |
| `role` | `admin` · `operator` · `viewer` |
| `enabled` | 정지면 로그인 거부. 과거 이력은 유지 |
| `created_at` / `updated_at` | UTC ISO |
| `created_by` | 만든 작업자 id. 최초 관리자는 `null` |

삭제: **하드 삭제 없음**. 정지만. 이력이 가리키는 사람이 사라지면 안 된다.

### 42.2 역할

| 역할 | 할 수 있는 것 | 못하는 것 |
|------|----------------|-----------|
| `admin` | 전부. 작업자 CRUD, 마법사 재진입, 락 강제 해제 | 이력 삭제 |
| `operator` | 구성 보드, 시작/정지/일시중지, 파일·변수, 로그, 스니프, 이력 **조회** | 작업자 생성/역할 변경, 락 강제 해제 |
| `viewer` | 대시보드, 로그 읽기, 스니프, 이력 조회 | 모든 POST/PATCH/PUT/DELETE (로그인·자기 비밀번호 변경 제외) |

`pidpau`는 어떤 역할에도 웹 버튼이 없다.

### 42.3 최초 관리자

작업자 테이블이 비어 있으면 로그인 대신 **부트스트랩**만 연다.

1. 초기 설정 마법사 마지막 칸: 관리자 ID·표시 이름·비밀번호(10자 이상).
2. 이미 마법사만 끝난 기존 설치: `POST /api/auth/bootstrap` 한 번. 이후 403.
3. 환경 변수 `EW_WEB_BOOTSTRAP_USERNAME` / `EW_WEB_BOOTSTRAP_PASSWORD` 는 **개발·CI 전용**. 파일이 비어 있을 때만 시드하고, 배포 README는 변수를 비우라고 한다.

관리자가 0명이 되도록 마지막 admin을 정지하면 거부한다.

### 42.4 세션

| 항목 | 규칙 |
|------|------|
| 로그인 | `POST /api/auth/login` `{ username, password }` |
| HTTP | HttpOnly `ew_session` 쿠키. 브라우저 프론트는 `credentials: include`. `X-API-Key` 공유키는 **사람 UI에서 제거** |
| 만료 | 유휴 12시간, 절대 7일. 로그아웃 `POST /api/auth/logout` |
| WS | 쿼리에 비밀번호를 넣지 않는다. `POST /api/auth/ws-ticket` → 60초 티켓 → `/ws/*?ticket=` |
| 서비스 계정 | 선택. `EW_WEB_API_KEY`가 있으면 합성 작업자 `service` (`role=operator`). pytest·스크립트용. 이력 `actor_username=service` |
| 실패 | 같은 username 5회/10분이면 10분 잠금. 이력 `login_failed` (비밀번호 없음) |

자기 비밀번호 변경: `POST /api/auth/password`. admin은 다른 사용자에게 **임시 비밀번호 재설정**만 (새 해시 저장, 평문 이력 금지).

---

## 43. 이력 모델

테이블 `audit_event`. append-only. UPDATE/DELETE 쿼리를 애플리케이션이 호출하지 않는다.

| 컬럼 | 내용 |
|------|------|
| `id` | 정수 PK |
| `at` | UTC |
| `actor_id` | 작업자 id. 부트스트랩·service는 nullable + `actor_username` 필수 |
| `actor_username` | 당시 로그인 ID |
| `actor_display_name` | 당시 표시 이름 |
| `action` | 아래 코드 |
| `target` | 예: `q3302ew_sta1`, `startstop_unix.d`, `compose` |
| `result` | `ok` · `error` · `denied` |
| `ip` | 요청 주소. X-Forwarded-For는 신뢰 프록시일 때만 |
| `detail` | JSON. 비밀 키 없음. AuthCode·비밀번호·API 키 마스킹 |
| `backup_dir` | compose/파일 적용 시 `web_backup/…` 상대 경로 |

### 43.1 반드시 기록하는 동작

| `action` | 때 |
|----------|-----|
| `login` / `logout` / `login_failed` | 인증 |
| `bootstrap_admin` | 최초 관리자 |
| `operator_create` / `operator_update` / `operator_disable` | 작업자 |
| `setup_complete` | 마법사 종료 |
| `compose_apply` | 일괄 적용 (revision, 인스턴스 id 목록) |
| `control_start` / `control_pau` | 전체 |
| `control_stopmodule` / `control_restart` | pid·모듈 이름 |
| `module_toggle` / `module_clone` / `module_delete` | |
| `file_write` | 경로 basename만 |
| `variables_apply` | 키 이름. 값 중 비밀 제외 |
| `lock_unlock` | |
| `sniff_start` / `sniff_stop` | 도구 이름. 링 이름 |

`compose_validate`·`GET`·status 폴링은 **안 남긴다** (噪声). `denied`(403)는 남긴다.

### 43.2 조회 · 보관

| 항목 | 규칙 |
|------|------|
| API | `GET /api/audit?from&to&actor&action&result&q` 페이지 50 |
| UI | 네비 **이력**. 테이블 + 필터. viewer도 읽기 |
| 내보내기 | `GET /api/audit/export` CSV. admin·operator |
| 보관 | `audit_retention_days` 기본 **365**. 일일 스윕이 오래된 줄만 삭제(이 삭제만 예외이며 `audit_sweep` 한 줄로 남김) |
| EW 로그 보관 | 기존 14일과 **별개** |

이력을 고치는 UI는 없다.

---

## 44. API · 화면

| 메서드 | 경로 | 권한 |
|--------|------|------|
| POST | `/api/auth/bootstrap` | 테이블 공백일 때만 |
| POST | `/api/auth/login` | 공개 |
| POST | `/api/auth/logout` | 로그인 |
| GET | `/api/auth/me` | 로그인 |
| POST | `/api/auth/password` | 본인 |
| POST | `/api/auth/ws-ticket` | 로그인 |
| GET/POST | `/api/operators` | admin |
| PATCH | `/api/operators/{id}` | admin |
| GET | `/api/audit` | 로그인 |
| GET | `/api/audit/export` | admin, operator |

프론트:

- `Login.tsx` — 부트스트랩/로그인 분기
- 헤더: 표시 이름 · 역할 · 로그아웃
- `Operators.tsx` — admin만 네비 **작업자**
- `Audit.tsx` — **이력**
- viewer는 구성 보드·제어 버튼 숨김 (API도 403)

미들웨어: 변경 핸들러가 반환한 뒤 `audit_event` insert. 핸들러 예외도 `result=error` + 메시지 요약(스택 없음).

---

## 45. 단계 · MVP

[plan_mvp.md 31절](plan_mvp.md)을 이 규칙으로 고친다.

| 단계 | 작업자·이력 |
|------|-------------|
| 1 마법사 | 마지막에 최초 admin 칸 추가 (2b와 함께) |
| 2 제어 | 기존. 2b 이후 호출에 actor 필요 |
| **2b 작업자·이력** | **MVP**. 로그인, 3역할, 이력 화면, 변경 API 기록 |
| 3 카탈로그 | 로그인 필요 |
| 4 구성 보드 | `compose_apply`에 작업자 필수. 2b 없이 4를 머지하지 않음 |
| 5 로그 | 모듈 로그와 이력 화면을 헷갈리지 않게 라벨 |
| 6 배포 | SSO·프록시 TLS. 이력 자체는 6에 미루지 않음 |

공유 키만으로 사람이 쓰는 UI를 남기지 않는다. pytest는 `service` 키 또는 테스트 로그인 픽스처.

### 수락 (2b)

1. 부트스트랩 없이 변경 API → 401
2. viewer로 `POST /api/control/start` → 403 + 이력 `denied`
3. operator로 pau → 이력 `control_pau` ok, 표시 이름 일치
4. 비밀번호가 audit `detail`에 없음
5. 마지막 admin 정지 거부
6. 이력 UI에서 시간·작업자 필터

---

## 46. 위험

| 위험 | 완화 |
|------|------|
| 공유 키를 헤더에 계속 씀 | 사람 UI는 세션만. 키는 service |
| WS `?key=`에 비밀번호 | 짧은 ticket |
| AuthCode가 이력 JSON에 복사됨 | detail 마스킹 목록 (`AuthCode`, `password`, `API_KEY`) |
| SQLite 잠금 | WAL. 이력 insert 실패해도 본 요청은 이미 성공했을 수 있음 → 로그 경고, 재시도 1회 |
| 누가 했는지 없는 적용 | 4단계 머지 가드: actor 없으면 apply 500 |
| 작업자=리눅스 ew 유저로 착각 | README: 웹 작업자는 콘솔 신원. startstop uid는 호스트 계정 |

---

## 47. 현재 코드 갭

| 위치 | 갭 |
|------|-----|
| `security.py` | 공유 키만. 세션·역할 없음 |
| `app.json` | 사용자·이력 없음 |
| 프론트 | `VITE_API_KEY` 전역. 로그인 화면 없음 |
| 변경 API | actor 인자 없음 |
| 네비 | 작업자·이력 항목 없음 |

이 파일이 닫히는 조건: 로그인 후 적용·기동이 이력 테이블에 작업자 이름으로 남고, admin이 작업자를 등록·정지할 수 있으며, viewer는 변경을 못한다.
