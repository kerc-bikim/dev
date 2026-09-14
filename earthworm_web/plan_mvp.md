# 단계별 세부 계획 · MVP

이 문서는 [plan.md 12절](plan.md)과 [plan_priority.md 27절](plan_priority.md)을 **실행 단위**로 쪼갠다. 각 단계의 목표, 넣을 것/빼는 것, API·화면·테스트, 수락 조건을 적는다.

전제: 백엔드는 FastAPI, 프론트는 React. 프론트는 Earthworm 바이너리를 직접 호출하지 않는다. 제어 규칙은 그대로다 (`startstop` / `pau` / `stopmodule <pid>` / `restart <pid>`, `pidpau` 웹 금지, 첫 링 `STATUS_RING`).

[단계 지도](diagrams/phase-roadmap.html)

[MVP 범위](diagrams/mvp-scope.html)

---

## 30. MVP 한 줄

**MVP**는 작업자가 로그인한 뒤, 우선 I/O 모듈을 **한 창에서 여러 인스턴스로 등록·입력·검증·적용**하고, 같은 `startstop`으로 **함께 기동·정지**하며, **누가 무엇을 했는지 이력**으로 확인하는 최소 제품이다.

MVP가 **새로 닫는 갭**은 **2b 작업자·이력**, 3단계(화이트리스트·스키마·시드), 4단계(구성 보드·일괄 적용)다. 1·2단계와 로그·스니프는 이미 코드에 있으므로 **재구현하지 않고 전제로 쓴다.** 공유 `EW_WEB_API_KEY`만으로는 작업자를 구분할 수 없으므로, 4단계 적용보다 **2b를 먼저** 머지한다.

MVP가 **성공한 장면** (시드 홈만으로도, 실제 `EW_HOME`이 있으면 더 좋음):

1. 최초 관리자를 만들고 로그인한다.
2. 운영자 계정을 하나 등록한다.
3. 운영자로 구성 보드에서 `q3302ew` 두 장 등을 적용하고 시작한다.
4. 이력에 그 운영자 이름과 `compose_apply` / `control_start`가 남는다.
5. 조회자 계정은 시작 버튼이 막히고, 이 거절도 이력에 남는다.
6. 모듈 로그·스니프는 기존 화면으로 본다 (이력 화면과 별개).

이 장면 밖(기타 `bin` 등록, `getmenu`, systemd 패키지, WEB_DOC, NTP 위젯)은 **MVP 이후**다. 파일 편집 화면이 우회 경로로 남는다.

---

## 31. 단계와 MVP의 관계

| 단계 | 이름 | 코드 상태 | MVP |
|------|------|-----------|-----|
| 0 | 기반(이미 있음) | 마법사·제어·대시보드·파일·로그·스니프·clone API | **전제**. 손대지 않거나 보드가 호출만 함 |
| 1 | 초기 설정 마법사 | 있음 | 전제. 2b와 함께 최초 admin 칸 |
| 2 | 제어와 대시보드 | 있음 | 전제. 2b 이후 actor 필수 |
| **2b** | **작업자·이력** | 있음 | **MVP에 포함**. [plan_ops.md](plan_ops.md) |
| 3 | 우선 카탈로그·스키마 | 있음 | **MVP에 포함** |
| 4 | 구성 보드·일괄 적용 | 있음 | **MVP에 포함**. apply에 작업자 필수 |
| 5 | 로그·링 모니터 | 대부분 있음. `getmenu` 없음 | 기존 화면은 MVP에 포함. `getmenu`는 이후 |
| 6 | 다듬기·배포 | `earthworm_web/compose.yaml` | 이 앱만 Docker. SSO·WEB_DOC는 이후 |

구현 순서는 **2b → 3 → 4** (3과 2b는 병렬 가능, **4는 2b 이후**). 작업자 없는 적용은 이력이 아니다.

---

## 32. 1단계 — 초기 설정 마법사 (전제, 동결)

### 목표

`ew_linux.bash`로 `EW_HOME`/`EW_PARAMS`/`EW_LOG`/`EW_DATA_DIR`·Inst를 고정하고, 링 테이블과 `startstop_unix.d` 뼈대를 만든다. 끝나기 전 제어 API는 409.

### 이미 있는 것

- `/api/setup/*`, SetupWizard, `STATUS_RING` 첫 줄, `FLAG_RING` 제외
- params 부트스트랩, Inst/테이블 검증
- 파일 트리 편집 (`/api` files)

### MVP에서 할 일

새 기능 없음. 3–4단계가 마법사 `setup_complete` 가드를 깨지 않는지 회귀 테스트만 유지.

### 넣지 않는 것

링 크기 변경을 기동 중에 허용하기. 재진입은 기존처럼 `pau` 후 기반 설정.

### 수락

- 마법사 완료 전 `/api/control/start` 409
- 완료 후 `EW_PARAMS`에 링·startstop 파일이 있다
- pytest `test_api_flow` 의 setup 경로 통과

---

## 33. 2단계 — 제어와 대시보드 (전제, 동결)

### 목표

같은 호스트에서 Earthworm 전체를 기동·종료하고, pid 기준으로 모듈을 잠시 멈추거나 재개한다. 상태를 대시보드와 `/ws/status`로 본다.

### 이미 있는 것

- Start=`startstop`, Stop=`pau`, Pause=`stopmodule <pid>`, Resume=`restart <pid>`
- 락파일·IPC 진단, KillDelay 폴링
- 기동 중 토글 ↔ stopmodule / reconfigure
- HTTP `X-API-Key`, WS만 `?key=`

### MVP에서 할 일

구성 보드의 **시작** 버튼이 기존 control API를 호출하게만 연결. 제어 규칙을 바꾸지 않는다. Alive 중 적용은 파일만 쓰고 “restart 필요” 배지(4단계에서 추가).

### 넣지 않는 것

이름 인자로 중지, `pidpau` 웹 버튼, 여러 startstop.

### 수락

- 시드 스텁에서 start → status 파싱 → pau
- 한 모듈 pause/resume이 pid 인자인지 argv 테스트로 확인

---

## 33b. 2b단계 — 작업자·이력 (MVP)

상세 모델·API는 [plan_ops.md](plan_ops.md). 요약만 둔다.

### 목표

사람마다 로그인하고, 변경 API마다 작업자 이름을 이력에 남긴다. 관리자는 작업자를 등록·정지한다. 모듈 `*_YYYYMMDD.log`와 이력 화면은 분리한다.

### 넣을 것

- SQLite `control.sqlite`: operators, sessions, audit_event
- 역할 `admin` / `operator` / `viewer`
- 최초 admin 부트스트랩 (마법사 마지막 칸)
- 로그인 세션 쿠키. WS는 짧은 ticket
- 네비 **작업자**(admin) · **이력**(전원 조회)
- 변경 성공/실패/403을 append-only로 기록. 비밀번호·AuthCode 마스킹

### 빼는 것

SSO, 리눅스 계정 동기화, 이력 삭제 UI, 사람 UI의 공유 API 키

### 수락

viewer의 start는 403+이력 `denied`. operator pau는 이력에 표시 이름. 마지막 admin 정지 거부.

### 순서

**4단계 apply 전에 머지.** actor 없는 적용은 거부한다.

---

## 34. 3단계 — 우선 카탈로그와 스키마 (MVP)

### 목표

팔레트에 **우선 모듈만** 보이게 하고, 각 Process 패밀리의 1차 필드를 JSON으로 프론트에 준다. 시드에 I/O 12개 스텁과 샘플 `.d`가 있어 실제 tarball 없이도 보드를 시험한다.

### 넣을 것

| 항목 | 내용 |
|------|------|
| `module_fields.yaml` | family, `role`, `fleet`, 1차 `fields[]` (22절 키만) |
| `GET /api/modules/schema` | YAML → JSON |
| `catalog()` | `priority`, `role`, `fleet`, `clone_of` |
| 시드 | 12 I/O + 기존 CONTROL_BINS 스텁, 최소 `.d`/`.desc` |
| 팔레트 UI | 우선 12. fleet는 `+` = 인스턴스 추가 예고(실제 복사는 4단계 apply). 비-fleet는 카드 하나 |
| 카탈로그 필터 | 기본 `priority`. “전체 bin”은 보기 전용(등록은 4단계 이후) |

### 빼는 것 (MVP 밖)

- `POST /api/modules/register` (기타 모듈). 우회는 파일 편집
- 매뉴얼 전 키를 폼으로 올리기
- `getmenu`를 팔레트 Process로 오인

### API

| 메서드 | 경로 | 비고 |
|--------|------|------|
| GET | `/api/modules` | 기존 + `priority`/`role`/`fleet` |
| GET | `/api/modules/schema` | 신규 |

기존 clone API는 유지. 3단계 UI는 clone을 직접 호출하지 않고 4단계 apply에 맡기는 것이 원칙이다. 3단계만 머지된 중간 상태에서는 기존 Modules 토글이 깨지면 안 된다.

### 화면

`Modules.tsx`에 팔레트 그룹(I/O · 제어 안내 · 진단 안내). 제어/진단은 카드가 아니라 “대시보드/링 모니터로” 링크. 아직 보드 레이아웃이 없으면 기존 토글 목록 위에 팔레트만 얹는다.

### 테스트

- YAML 로드, 12 family 존재, fleet 5개 플래그
- 시드 후 `bin`에 `q3302ew` 등 실행 비트
- 카탈로그 기본 응답에 `pick_ew`가 없거나 `priority: false`
- 프론트 `tsc --noEmit`

### 수락

운영자가 모듈 설정에서 **우선 12 + 필수 statmgr**만 또렷이 보고, 스키마 API가 `q3302ew.fields`에 `IPAddress`를 돌려준다.

### 완료 정의

3단계 단독으로 일괄 적용은 하지 않는다. 다음 단계의 입력이다.

---

## 35. 4단계 — 구성 보드와 일괄 적용 (MVP 핵심)

### 목표

한 창에서 인스턴스를 늘리고 1차 파라미터를 채운 뒤, **검토 → 적용 → 시작**으로 전체가 같이 돌아간다.

### 넣을 것

| 항목 | 내용 |
|------|------|
| `GET /api/compose` | 디스크+clones → 보드 모델 |
| `POST /api/compose/validate` | 쓰기 없이 이슈 목록 |
| `POST /api/compose/apply` | 스냅샷 + clone/패치 + Process 줄. 옵션 `reconfigure` |
| `POST /api/compose/suggest` | 이름·포트·탱크 제안 |
| `Compose.tsx` | 사이트 공통 + 팔레트 + 카드 + 적용 바. 네비 라벨 “모듈 설정” |
| 사이트 공통 | HeartbeatInt, 기본 WAVE_RING, Inst 표시. 기존 카드 덮어쓰기는 체크 시에만 |
| 1차 필드 | 22절 표. 고급은 원문 `.d` |
| 검증 | `dup_process`, `dup_module_id`, `dup_listen`, `dup_tank`, `missing_ring`, `missing_bin`, `max_child`, `cmd_len`, `bad_name`, `empty_required`, `ephemeral_port`(경고) |
| 롤백 | `backend/data/backups/compose-<ts>/` |
| AuthCode | password 입력, 서버 로그·이력 마스킹 |
| actor | 세션 작업자 필수. 없으면 apply 500 |

적용은 내부에서 기존 `clone_module`을 여러 번 호출한다. 중간 실패 시 그 apply가 만든 파일만 되돌린다.

### 빼는 것 (MVP 밖)

- 기타 모듈 등록 모달
- Variables 페이지 삭제(보드는 사이트 바를 갖고, Variables는 남겨도 됨)
- 기동 중 `.d` 핫 리로드 (배지 + 수동 restart만)
- bin 원본 해시 비교 후 재복사
- StationXML에서 `Send_scnl` 자동 채움
- 공통 전파로 모든 카드 HeartbeatInt 강제 덮어쓰기(기본 끔)

### 화면 조작 (MVP 데모 스크립트)

1. 팔레트 `q3302ew` + 두 번 → `q3302ew_sta1`, `q3302ew_sta2` (제안 이름 수정 가능)
2. `slink2ew` +, `export_scnl` +, `wave_serverV` + (원본 이름 또는 `_n1`)
3. 필수 칸 입력. 같은 `ServerPort`를 두 export에 넣으면 검토가 빨강
4. 적용 → 시작. 대시보드에서 이름 확인
5. 카드 삭제 후 적용 = 기존 복제 삭제(기동 중이면 stopmodule 먼저)

`statmgr` 카드는 삭제 불가.

### 테스트

- 같은 리슨 포트 두 장 → validate 409, 디스크 불변
- apply 후 `earthworm.d` Module 유일, `startstop_unix.d`에 `q3302ew_sta1 q3302ew_sta1.d`
- Tank 경로 중복 거부
- `MAX_CHILD` 초과 거부
- apply 실패 롤백 (두 번째 clone을 강제 실패시키는 테스트)
- `SAFE_NAME` 위반 400

### 수락

시드만으로 pytest가 validate·apply를 통과하고, 브라우저(또는 preview)에서 카드 여러 장을 한 번에 적용할 수 있다. 이 단계가 끝나야 MVP가 닫힌다.

---

## 36. 5단계 — 로그와 링 모니터 (기존=MVP, 확장=이후)

### 목표

기동 후 운영자가 파일 로그와 링 내용을 본다.

### 이미 있는 것 (MVP에 포함)

- 로그 디렉터리·보관일·뷰어·follow. lock/data 제외
- sniffwave / sniffring 세션 2개, WS, 서버 줄 상한

### MVP에서 할 일

새 기능 없음. 보드에서 기동한 인스턴스 로그 파일 이름이 `{id}_YYYYMMDD.log` 패턴과 맞는지 스모크만.

### 이후 (MVP 밖)

- `getmenu` → 선택 wave_serverV IP:포트
- 기반 설정 재진입 UX 다듬기

### 수락 (MVP)

기존 Sniff·Logs 페이지가 보드 적용 이후에도 동작한다. sniff 세션 한도 2 유지.

---

## 37. 6단계 — 다듬기와 모노레포 배포 (MVP 밖)

### 목표

웹 콘솔은 Docker Compose 로 올리고, Earthworm 바이너리는 `EW_HOME` 볼륨(또는 호스트)에 둔다.

### 넣을 것 (이후)

- `earthworm_web/compose.yaml` 안정화, 태그 `earthworm-web-v0.x`
- WEB_DOC 정적 `/docs/ew/`
- NTP·디스크 위젯
- 기타 모듈 등록 API
- tankplayer는 등록으로만
- SSO (작업자 모델은 2b에서 끝냄)
- 호스트 전용 systemd 유닛(선택)

### MVP에서 허용하는 최소

README에 `docker compose up` 과 “배포 시 `EW_WEB_AUTO_SEED=0`, `EW_WEB_BASH`, 키를 `dev`에서 바꿀 것”이 있다. 실제 EW 기동은 override.

### 빼는 것

루트 npm/pnpm workspace 로 프론트를 한 lock 에 묶기, 이미지에 Rocky tarball 넣기, 프론트 마이크로프론트 합성.

---

## 38. MVP 범위 표

| 기능 | MVP | 이후 |
|------|-----|------|
| 마법사·링·Inst | ○ 기존 | |
| start / pau / stopmodule / restart | ○ 기존 | |
| 대시보드 + `/ws/status` | ○ 기존 | |
| 파일 편집 (우회) | ○ 기존 | |
| 로그·sniff | ○ 기존 | getmenu |
| 로그인·역할·작업자 CRUD | ○ 신규 2b | SSO |
| 변경 이력 화면 | ○ 신규 2b | 이력 삭제(하지 않음) |
| 우선 12 스키마·시드 | ○ 신규 | 필드 확장 |
| 구성 보드 한 창 | ○ 신규 | |
| 복제 다발 5종 인스턴스 추가 | ○ 신규 | |
| 검토·적용 트랜잭션 | ○ 신규 | 원본 bin 재복사 |
| 기타 모듈 등록 | | ○ |
| Variables 페이지 제거 | | ○ (보드는 사이트 바) |
| Compose·태그·WEB_DOC | | ○ |
| StationXML·PPSD 연동 | | ○ |
| `pidpau` 웹 버튼 | 하지 않음 | 하지 않음 |

---

## 39. MVP 수락 테스트

자동화 (시드, Earthworm 실기동 불필요):

1. 부트스트랩 admin → login
2. viewer로 start → 403, 이력 `denied`
3. operator로 compose apply(포트 다른 q3302ew 두 장) → Process 두 줄 + 이력 `compose_apply`
4. schema에 fleet 5 + process 12
5. 같은 `ServerPort` 두 `export_scnl` → validate 실패, 파일 없음
6. 같은 Tank 두 `wave_serverV` → 실패
7. 잘못된 이름 → 400
8. 기존 start/pau argv 테스트 회귀
9. audit detail에 password 없음

수동 (스텁 또는 실기):

1. 관리자가 운영자를 등록
2. 운영자로 보드 적용·시작
3. 이력에서 이름·동작 확인
4. 대시보드 일시중지, 로그·sniff

실기 Rocky 바이너리가 없는 환경에서는 자동화가 MVP 통과 기준이다.

---

## 40. 작업 쪼개기 (구현 착수 시)

2b 티켓 (4보다 먼저):

1. SQLite operators + bootstrap + login/session
2. 역할 가드 + 프론트 Login · 헤더
3. audit_event 미들웨어 + 이력 UI + 작업자 CRUD

3단계 티켓:

1. `module_fields.yaml` + 로더 + schema 엔드포인트
2. catalog 플래그 + 시드 12 스텁
3. 팔레트 UI (토글 목록과 공존)

4단계 티켓:

1. compose 모델 GET + validate
2. apply 트랜잭션 + 롤백 pytest
3. Compose 화면 + 적용 바 + control start 연결
4. 제안 포트/이름 API

한 티켓이 머지돼도 기존 마법사·제어가 깨지면 안 된다. MVP 태그는 4단계 3번까지 끝난 시점의 `earthworm-web-v0.1.0`을 권장한다.
