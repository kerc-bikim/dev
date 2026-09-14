# recvQSCD20 (GUI v1.0)

KIGAM QSCD20 UDP 패킷(120바이트)을 수신·기록·시각화하는 PyQt5 GUI입니다.

**매뉴얼:** [README.html](README.html) (도움말 F1). Time Diff 다이어그램은 HTML 개요에 있습니다.

## 요구 사항 · 설치

- Python 3.8+
- `pip install -r requirements.txt` (PyQt5, PyQtWebEngine, pyqtgraph, numpy)

```bash
python recvQSCD20_gui.py
```

버전: **1.0** (`VERSION` · `GUI_VERSION`)

## 변경 이력 (v1.0)

현재 버전을 **1.0**으로 두고, 이 버전에 들어 있는 기능을 정리합니다. 이전 3.x 중간 번호는 더 이상 나열하지 않습니다.

| 영역 | 내용 |
|------|------|
| 수신·저장 | 전용 프로세스가 UDP와 TimeDiff를 확정. `.QSCD.log`(상세 UTC)와 `.QSCD20.replay`(패킷+TimeDiff) 저장. 큐가 가득 차면 새 패킷을 버리고 먼저 받은 기록을 지킴. Stop 시 남은 패킷을 모두 기록 |
| Live | 관측소(Station+Location)마다 카드. PGA 현재값·선택 시간 창 누적 최대·수신 시각 타임시리즈. LATENCY는 TimeDiff, 미수신이 길면 빨간색 지연 초 |
| Detail View | 한 관측소의 Diff / Maximum / PGA / WMMA / TMM. 최종 수신 지연 깜빡임, 줌·호버·1초 격자 |
| File View | replay 재생. 저장 TimeDiff를 다시 계산하지 않음. 짝 `.QSCD.log`와 줌 구간 연동 |
| 로그·설정 | 로그 뷰어 하단 관측소 콤보(Ctrl+L). 기본 설정(Ctrl+P). 도움말(F1). 화면 KST/UTC, 저장은 UTC |

화면별 동작은 아래 **UI 명세**와 F1 도움말에 있습니다.

## 메뉴

| 메뉴 | 단축키 | 설명 |
|------|--------|------|
| **기본 설정** | Ctrl+P | `recvQSCD20_gui_settings.json` 편집 |
| **도움말** | F1 | README.html. Linux는 WebEngine GPU를 끄고, 실패 시 기본 HTML 뷰어 |
| **로그 뷰어** | Ctrl+L | 탭에 따라 수신 로그 또는 File 로그. 각 탭 상단 우측 아이콘과 동일 |

## UI 명세

메인 창은 왼쪽 **탭**(Live / Detail View / File View)과 오른쪽 **수신 패널**입니다.

### 우측 수신 패널 (세 탭 공통)

| 항목 | 설명 |
|------|------|
| 로그 파일명 (prefix) | 저장 파일 앞부분. 경로 문자, `..`, `<>:"\|?*`, 제어 문자, 끝 점·공백, Windows 예약 이름 불가. 같은 이름이 있으면 Start 시 덮어쓰기 확인 |
| 저장 경로 | 기본 설정의 `log_save_dir` / `bin_save_dir` (기본 `logs`, `bin`) |
| UDP Port | 기본 `default_port` (보통 9908) |
| Start / Stop | 수신 시작·중지. Stop은 큐 잔여 패킷을 기록한 뒤 파일을 닫음 |
| 상태 | 대기 중 / 수신 중 |

생성 파일: `{prefix}.QSCD.log`, `{prefix}.QSCD20.replay`.

### 공통 컨트롤

- **시간 선택:** 탭마다 콤보. 목록 `time_window_choices`, 기본 `default_time_window_sec`.
- **KST / UTC:** 탭 상단·로그 뷰어 하단. 화면만 바꿈. 파일과 TimeDiff 계산은 UTC.
- **로그 아이콘:** Live·Detail View는 수신 로그, File View는 짝 `.QSCD.log`.

### Live 탭

수신 중인 모든 관측소를 카드로 보여 줍니다. 키는 Station + Location입니다.

**상단:** 시간 선택(타임시리즈 폭·누적 최대 구간), PGA H/T 체크(둘 다 끌 수 없음), KST/UTC, 로그 아이콘.

**카드**

| 영역 | 내용 |
|------|------|
| 왼쪽 사이드바 | Station Code, Location Code(`0x00` → 문자 `0`), Quality, **LATENCY (SEC)**, Last Data (`HH:MM:SS`) |
| LATENCY | 평소: 마지막 패킷 TimeDiff(소수 3자리). 타이머로 다시 계산하지 않음. TimeDiff가 경고 시간(기본 10초)을 넘거나, 그 시간 동안 패킷이 없으면 빨간색. 미수신 시에는 경과 초(소수 1자리) |
| 현재 값 | 마지막 PGA H/T (gal) |
| 누적 최대 | 선택한 시간 창 안의 H/T 최댓값과 그때의 데이터 시각 |
| 타임시리즈 | x = 수신 시각(지금 기준 창), y = gal, 곡선 H·T, 호버 팝업 |

### Detail View 탭

한 관측소의 상세 시계열입니다. x축은 **데이터 시각**입니다.

**상단:** 수신 관측소 콤보(로그 뷰어 하단과 동기화), 최종 수신(지연 시 빨간 깜빡임과 `⚠ N초 지연`), Quality / Station / Location, KST/UTC, 로그 아이콘.

**그 아래:** 시간 선택, 범례·최근값 표시, 표시 차트 선택.

| 패널 | 곡선 | y축 |
|------|------|-----|
| Time Diff (recv − data) | Diff | 초 |
| Maximum (Z, N, E) | Z N E | gal |
| PGA (H, T) | H T | gal |
| U-D / N-S / E-W WMMA | m, M, A | gal |
| U-D / N-S / E-W TMM | m, M, A | gal |

차트: 1초 격자·빈 초 NaN, gal은 SI 접두 없이 실제 값, 상단 최근값(`— Z : 0.123456`)은 범례와 같은 색, 호버 말풍선, 드래그 줌 / 더블클릭·⟲ 초기화. 수신 중에는 최신 쪽으로 스크롤하다가, 사용자가 줌하면 멈춥니다.

시작 시 켜둘 패널·범례는 `default_panels` / `default_show_legend`(재시작 후 반영).

### File View 탭

저장된 replay를 엽니다.

- **QSCD20.replay 열기…** — 매직 `QCDX\x01`, 레코드 128B
- 시간 선택, 관측소 콤보(로그 뷰어와 동기화), 범례·패널은 Detail View와 같음
- Diff는 파일에 있는 TimeDiff를 그대로 사용
- 로그 아이콘: 같은 prefix의 `.QSCD.log`. 차트 줌 구간의 data time에 로그를 맞출 수 있음

### 로그 뷰어 (수신)

Live·Detail View에서 엽니다. 화면은 선택 관측소 패킷 + 시스템 메시지. 디스크 로그는 항상 상세 UTC입니다.

하단: 관측소 콤보, 상세 로그 표시(체크는 저장하지 않음), KST/UTC, 로그 지우기. 최대 줄 수 `log_max_lines`.

### 로그 뷰어 (File)

replay를 연 뒤에만 엽니다. 하단 관측소, 「차트 줌 구간에 맞추기」, 다시 읽기, 로그 파일 찾아보기, KST/UTC.

### 기본 설정 (Ctrl+P)

| 항목 | 설명 |
|------|------|
| `log_save_dir` / `bin_save_dir` | 로그·replay 폴더 |
| `default_port` | 우측 패널 기본 포트 |
| `default_time_window_sec` / `time_window_choices` | 시간 콤보 |
| `default_panels` / `default_show_legend` | 시작 시 차트·범례 (**재시작 후**) |
| `log_max_lines` | 로그 뷰어 최대 줄 |
| `chart_refresh_ms` / `packet_drain_max` | 갱신 주기·배치 크기 |
| `packet_queue_max` | 수신 큐 상한 (**다음 Start부터**) |
| `bin_flush_every` | replay flush 주기(패킷 수) |
| `recv_delay_alert_sec` / `recv_alert_blink_ms` | 지연 경고·깜빡임 |
| `sock_timeout_sec` / `sock_timeout_count` | UDP timeout (최소 0.05초) |
| `display_tz` | 화면 시간 기본값 |

변경 불가: `BIN_FILE_MAGIC` (`QCDX\x01`).

### 도움말 (F1)

README.html. Linux에서 Chromium GPU 컨텍스트 오류를 피하기 위해 GPU를 끕니다.

## 사용 순서

1. 필요하면 기본 설정에서 폴더·포트를 맞춘다.
2. prefix와 UDP 포트를 넣고 Start.
3. Live에서 전체 PGA를 보고, Detail View에서 한 관측소를 고른다.
4. Ctrl+L로 로그를 연다. 하단에서 관측소를 바꿀 수 있다.
5. Stop 후 File View에서 replay를 재생한다.

## 바이너리 (QSCD20.replay)

| 구간 | 크기 | 설명 |
|------|------|------|
| 헤더 | 5B | `QCDX\x01` |
| 레코드 | 128B | 패킷 120B + TimeDiff float64 (big-endian) |

TimeDiff = `recv_wall − myqscd[5]` (초). File View는 이 저장값을 그대로 씁니다.

## TimeDiff

```
데이터 시각 (myqscd[5])  |---- TimeDiff ----|  수신 시각 (recv_wall)
```

전용 수신 프로세스에서 확정하므로 탭 전환·로그·File View가 값에 들어가지 않습니다.

## 패킷 필드 (요약)

| 항목 | 인덱스 |
|------|--------|
| Quality Flag | [1] `0x00` Good / `0x01` GPS Unlock / `0x02` REBOOT / `0x03` SPIKE |
| Station Code | [4] `sta[5]` |
| Data Time | [5] Unix epoch |
| Location | [33] `char loc[2]`, `0x00` → 문자 `0` |
| WMMA / TMM | [6]–[20] |
| Maximum Z/N/E | [21]–[23] |
| PGA H/T | [24]–[25] |

이 프로그램은 120B 패킷을 받습니다. 온와이어 레이아웃은 이전 `2s+3s` 분할과 같아 기존 replay도 읽을 수 있습니다.

## loc 확인

```bash
python test_qscd20_loc.py
python test_qscd20_loc.py --file bin\sample.QSCD20.replay
python test_qscd20_loc.py --selftest
```

GUI와 같은 UDP 포트는 동시에 bind할 수 없습니다.
