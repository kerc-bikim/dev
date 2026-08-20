# recvQSCD20 (GUI v3.10)

KIGAM QSCD20 UDP 패킷(120바이트)을 수신·기록·시각화하는 PyQt5 GUI 프로그램입니다.

**매뉴얼 관리 대상:** [recvQSCD20_gui.py](recvQSCD20_gui.py) 만 해당합니다.

## 요구 사항

- Python 3.8+

## 설치

```bash
pip install -r requirements.txt
```

도움말 HTML 렌더링에 **PyQtWebEngine** 이 필요합니다 (`pip install PyQtWebEngine`).

## 실행

```bash
python recvQSCD20_gui.py
```

버전: **3.10** (`VERSION` · `GUI_VERSION`)

### 메뉴

| 메뉴 | 단축키 | 설명 |
|------|--------|------|
| **기본 설정** | Ctrl+P | [recvQSCD20_gui_settings.json](recvQSCD20_gui_settings.json) 편집 (팝업) |
| **도움말** | F1 | [README.html](README.html) 매뉴얼 (QWebEngineView 팝업) |

Live 탭 상단 우측 아이콘: **로그 뷰어** (Ctrl+L).

메인 창: **Live / File Viewer** 탭 + **우측 수신 패널**(로그 파일명, UDP Port, Start/Stop, 상태).

## 기본 설정 (설정 파일)

런타임 상수는 [gui_settings.py](gui_settings.py) · [recvQSCD20_gui_settings.json](recvQSCD20_gui_settings.json) 에서 관리합니다.  
메뉴 **기본 설정**에서 GUI로 수정·저장할 수 있으며, 항목에 마우스를 올리면 한글 설명이 표시됩니다.

| 항목 (예) | 설명 |
|-----------|------|
| `log_save_dir` | 텍스트 로그 저장 폴더 (기본 `logs`) |
| `bin_save_dir` | QCDX 바이너리 저장 폴더 (기본 `bin`) |
| `default_port` | 우측 패널 기본 UDP 포트 |
| `default_time_window_sec` / `time_window_choices` | 시간 콤보 기본값·목록 |
| `default_panels` / `default_show_legend` | 시작 시 차트 패널·범례 (**프로그램 재시작 후 반영**) |
| `log_max_lines` | 로그 뷰어 최대 줄 수 |
| `chart_refresh_ms` / `packet_drain_max` | Live 갱신 주기·1회 배치 처리량 |
| `packet_queue_max` | 수신 큐 상한 (**다음 Start부터 반영**) |
| `bin_flush_every` | 바이너리 flush 주기 (**패킷 수** 기준) |
| `recv_delay_alert_sec` / `recv_alert_blink_ms` | 수신 지연 경고 |
| `sock_timeout_sec` / `sock_timeout_count` | UDP 수신 스레드 (timeout 최소 `0.05`초, 수신 중에도 반영) |

설정 저장 시 즉시 반영되지 않는 항목은 저장 완료 창에서 따로 안내합니다.

**변경 불가 (코드 고정):** `BIN_FILE_MAGIC` (`QCDX\x01`) — QCDX 바이너리 포맷 식별자

### 로그 파일명(prefix) 규칙

경로 구분자, `..`, `<>:"|?*`, 제어 문자, 끝의 점·공백, Windows 예약 이름(`CON`, `NUL`, `COM1` 등)은 거부됩니다.
이미 같은 이름의 파일이 있으면 Start 시 덮어쓰기 여부를 확인하며, 승인하면 로그와 바이너리 모두 새로 기록합니다.

## 사용 방법

### 수신 (메인 우측 패널)

1. **로그 파일명 (prefix)** — 예: `20260519_120000`
2. **UDP Port** — 기본 `9908` (기본 설정에서 변경 가능)
3. **Start** / **Stop** · **상태** 표시

저장 경로는 **메뉴 → 기본 설정**의 `log_save_dir` / `bin_save_dir` (프로그램 디렉터리 기준 상대 경로 `logs`, `bin`).

| 파일 | 위치 |
|------|------|
| `{prefix}.QSCD.log` | `log_save_dir` |
| `{prefix}.QSCD20.replay` | `bin_save_dir` |

### Live 탭

1. **시간 선택** — 60 / 120 / 600 / 1200 / 1800초
2. **수신 관측소** — 선택 관측소만 화면 로그·차트 (최종 수신 KST, 10초 지연 시 빨간 깜빡임)
3. **Quality / Station / Location**
4. **범례·최근값 표시** — 체크 해제 시 차트 범례와 상단 최근값 함께 숨김
5. **표시 차트** — Diff, Maximum, PGA, WMMA, TMM
6. **차트** — KST x축, 1초 NaN 격자, 호버 팝업, 줌/⟲ 초기화
7. **상단 최근값** — `— Z : 0.123456` 형식, **범례와 동일 색상**
8. **로그** — Live 탭 상단 우측 **로그 뷰어** 아이콘 (Ctrl+L). 하단 **상세 로그 표시** 체크로 화면을 요약/상세로 다시 그림. 파일(`.QSCD.log`)은 항상 상세 저장.

### File Viewer 탭

- `QSCD20.replay 열기`, **관측소** 선택 (이전 `.bin` 파일도 열 수 있음)
- QCDX 파일: 저장된 **TimeDiff** 그대로 Diff 차트 표시
- 구형 120B-only (QCDX 헤더 없음): Diff 근사

## 바이너리 (QCDX)

| 구간 | 크기 | 설명 |
|------|------|------|
| 헤더 | 5B | `QCDX\x01` |
| 레코드 | 128B | 120B 패킷 + TimeDiff float64 |

## TimeDiff 와 수신 부하

TimeDiff(`recv − data time`)는 UDP 수신 스레드에서 확정합니다.
Linux에서는 커널 수신 시각(`SO_TIMESTAMPNS`)을 쓰고, 없거나 Windows이면 `recvfrom` 직후 `time.time_ns()`를 씁니다.
차트·로그 부하와 계산을 분리하고, 수신 스레드 우선순위를 높입니다.

큐가 `packet_queue_max` 까지 차면 **먼저 받은 기록을 지키기 위해 새로 들어온 패킷을 버리고**, 폐기 건수를 로그에 남깁니다.
Stop 시에는 큐에 남은 패킷을 모두 기록한 뒤 파일을 닫습니다.

## 패킷 필드 (요약)

| 항목 | 인덱스 |
|------|--------|
| Quality Flag | [1] |
| Station Code | [4]+[5] |
| Data Time | [6] |
| Location | [34] |
| Maximum / PGA / WMMA / TMM | 7–26 |

## HTML 문서

- [README.html](README.html) — 통합 매뉴얼 (도움말 메뉴에서 열림)
- [plan.html](plan.html) — 구현 계획

## 계획·상세

[plan.md](plan.md)
