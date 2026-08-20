# QSCD20 UDP 수신 GUI — 구현 계획 (plan)

**recvQSCD20_gui.py** 전용 PyQt5 + pyqtgraph GUI 프로젝트의 계획·구현 이력입니다.

**현재 버전: v3.9** ([recvQSCD20_gui.py](recvQSCD20_gui.py), [VERSION](VERSION))

HTML: [README.html](README.html) · [plan.html](plan.html) — 도움말 메뉴(F1)에서 README.html 로드

---

## 1. 목표 (최종)

| 항목 | 내용 |
|------|------|
| UDP 포트 | 메인 우측 패널, 기본 **9908** |
| 로그 / replay | `{prefix}.QSCD.log` → `logs/`, `{prefix}.QSCD20.replay` → `bin/` (QCDX) |
| 헤더 | Quality Flag, Station(5B), **Location**([34]) |
| Diff | `recvfrom() 직후 wall − data time`, QCDX 저장·File 재현 |
| 차트 | KST x축, 1초 NaN, 패널별 diff/max/pga/wmma/tmm |
| 범례·최근값 | 상단 `— label : value`, 범례 색상 동일; 체크로 on/off |
| 관측소 | Live·File 콤보 필터 |
| 수신 지연 | 10초 초과 시 최종 수신 빨간 깜빡임 |
| UI | Live/File 탭 + **우측 수신 패널**; 로그 뷰어는 Live 탭 아이콘, 기본 설정은 메뉴 |
| 도움말 | **README.html** QWebEngineView |
| 성능 | UDP 스레드 큐, 200ms 배치 drain, 활성 패널 격자 캐시 |

---

## 2. 파일 구성

| 파일 | 역할 |
|------|------|
| [recvQSCD20_gui.py](recvQSCD20_gui.py) | GUI **v3.9** |
| [gui_settings.py](gui_settings.py) | 설정 로드·검증·한글 툴팁 |
| [recvQSCD20_gui_settings.json](recvQSCD20_gui_settings.json) | 사용자 설정 |
| [test_gui_settings.py](test_gui_settings.py) / [test_recv_core.py](test_recv_core.py) | 단위 테스트 (`python -m unittest discover`) |
| [requirements.txt](requirements.txt) | PyQt5, PyQtWebEngine, pyqtgraph, numpy |
| [README.md](README.md) / [README.html](README.html) | 사용자 매뉴얼 |
| [plan.md](plan.md) / [plan.html](plan.html) | 본 문서 |
| [VERSION](VERSION) | 버전 번호 |

---

## 3. 의존성

```
PyQt5>=5.15.0
PyQtWebEngine
pyqtgraph>=0.13.0
numpy>=1.20.0
```

```bash
pip install -r requirements.txt
python recvQSCD20_gui.py
```

---

## 4. QSCD20 패킷 · QCDX 바이너리

- 패킷 120B, `QSCD20_FMT`
- QCDX: `QCDX\x01` + (120B + TimeDiff 8B) × N
- TimeDiff는 UDP `recvfrom()` 직후 캡처 (GUI 부하와 분리)
- `read_qscd20_bin()` / `pack_qscd20_bin_record()`

---

## 5. GUI 레이아웃 (v3.9)

### 메뉴

- 기본 설정 (Ctrl+P) — 저장 디렉터리·포트·타이머 등
- 도움말 (F1) → README.html

### Live / File Viewer

- Live 상단 우측: 로그 뷰어 아이콘 (Ctrl+L)
- 우측: prefix, UDP Port, Start/Stop, 상태
- MetaBar, 시간·범례 체크, 차트 패널
- 패널 헤더: 제목 · **최근값 라벨** · ⟲ 줌 초기화
- File Viewer: `QSCD20.replay` 열기

---

## 6. 모듈 요약

| 모듈 | 역할 |
|------|------|
| `UdpReceiver` | UDP 스레드, TimeDiff 확정, thread-safe 큐 |
| `StationBuffer` | 초 단위 버킷 |
| `QscdChartDashboard` | 차트·범례·최근값 |
| `ChartHoverTooltip` | 호버 팝업 |
| `PlainGalAxisItem` | gal 축 SI 비활성 |
| `HelpManualDialog` | README.html |
| `gui_settings` | JSON 설정 |

---

## 7. 버전 이력

| 버전 | 주요 내용 |
|------|-----------|
| v1–v2 | 초기 GUI, Diff, KST, 관측소 |
| v3 | NaN 격자, 성능 |
| v3.1 | 캐시 version, 줌 |
| v3.2 | QCDX, 다패널, 배치 수신 |
| v3.3 | 수신 설정·로그 메뉴 팝업, 메인=차트 |
| v3.4 | recvQSCD20_gui 전용 문서, 범례·최근값, F1 도움말 |
| v3.5 | 설정 파일 + 기본 설정 메뉴 |
| v3.6 | 우측 수신 패널, logs/bin 경로, TimeDiff 스레드 캡처 |
| v3.7 | thread-safe 수신 큐, flush·설정 적용 버그 수정, prefix 검증 |
| **v3.8** | 큐 포화 시 새 패킷 폐기(기록 보존), socket timeout 하한·스레드 적용, 종료 시 잔여 큐 기록, 예약 파일명 차단, 단위 테스트 |
| **v3.9** | 저장 확장자 `.QSCD20.replay`, 탭 이름 잘림 방지, 로그 뷰어를 Live 탭 아이콘으로 이동 |

---

## 8. 데이터 흐름

```
UDP Thread: recvfrom → time.time() → TimeDiff
         → queue.Queue (패킷당 Qt 시그널 없음, 포화 시 새 패킷 폐기)
GUI QTimer: drain(≤packet_drain_max) → bin/로그(확정 Diff) → 차트
Stop/종료 : 잔여 큐 전부 drain → flush → 파일 close
```

---

## 9. 구현 상태

**v3.9** 기준 **완료**.
