# RingWave — ringserver 실시간 WebGL 파형 뷰어

**버전 1.2.0** (2026-08-07)

EarthScope [ringserver](https://github.com/EarthScope/ringserver) WebSocket(**DataLink**)으로 실시간 miniSEED를 수신하고, WebGL(`webgl-plot`)로 파형을 표출합니다.

계획서: [plan.md](./plan.md) / [plan.html](./plan.html)

## 요구 사항

- Node.js 20+
- (선택) Conda 환경 `ringserver_seedlink_websocket` — 계획서 HTML 생성용 Python 3.12

## 빠른 시작

```bash
# 저장소 루트
cp .env.example .env   # Windows: copy .env.example .env
npm install
npm install --prefix backend
npm install --prefix frontend

npm run dev
```

- Frontend: http://localhost:5173  
- Backend API/Proxy: http://localhost:8787  

브라우저 요청은 Vite가 `/api`, `/ringserver`, `/fdsnws`를 백엔드로 프록시합니다. 백엔드는 설정 저장소의 URL로 ringserver·FDSNWS에 동적 프록시합니다.

레이아웃/설정은 `backend/data/app.json`에 저장됩니다 (Windows 네이티브 빌드 도구 불필요).

## 환경 변수 (`.env`)

```env
RINGSERVER_URL=http://localhost:18000
FDSNWS_URL=http://172.31.100.100/fdsnws
DATABASE_PATH=backend/data/app.json
PORT=8787
```

설정 모달에서도 ringserver / FDSNWS URL을 바꿀 수 있습니다.

## 주요 기능 (v1.2)

- Network → Station → Channel 트리 다중 선택 Plot
- 탑바 레이아웃 CRUD (`app.json`)
- DataLink 실시간 수신 (공유 WebGL 1캔버스)
- duration 기본 300s, 타임윈도우 스텝 15…7200s, 갱신 기본 0.5s
- 패널 최대 50, HTML5 DnD 순서 변경
- Calibration 아이콘: Raw / Physical 토글 (기본 Raw)
- Scale 아이콘: Auto / Uniform Y축 스케일
- Band-pass 필터(지진 3·공중음파 3·커스텀, 기본 Off) — 파형+FFT
- X축 오른쪽 기준: `now` / `lastData`
- 시간축 눈금·보조선, 갭 배지
- 전역 일시정지 + 마우스/터치 줌·팬
- 패널 FFT (Log F × Log Power dB)
- 설정 모달(톱니), 전체 스트림 닫기(✕✕)
- WS 자동 재연결 + 상태바 표시
- 모바일 드로어 UI

## 히스토리

### 1.2.0 — 2026-08-07

- 상태바 Band-pass 필터 아이콘(기본 Off)
- 지진 3·공중음파 3 프리셋 + 커스텀 추가/삭제(`app.json` 저장)
- Butterworth 4차 zero-phase를 표시 윈도우에 적용(파형·FFT)

### 1.1.0 — 2026-08-04

- 모바일: 핀치 줌인/아웃, 더블탭 초기화, 줌 후 한손가락 팬
- Y축 Scale Auto/Uniform (최대 진폭 패널 기준)
- Raw/Physical → Calibration 아이콘, 상태바 좌측 이동
- 전체 스트림 닫기(✕✕) + 확인 대화상자
- 모바일 설정 모달 하단 버튼 잘림 보정
- 줌 구간 파형 lookback 보정

### 1.0.0 — 2026-08-04

첫 정식 릴리스.

- DataLink + WebGL 파형 스택, Stream Plot, 레이아웃 CRUD
- 설정 모달 · 상태바(타임윈도우/줌/일시정지)
- X축 앵커·눈금, 패널 FFT(Log–Log)
- JSON 저장소, 자동 재연결, 모바일 대응

상세는 [plan.md §12 히스토리](./plan.md#12-히스토리)를 참고하세요.

## 계획서 HTML 재생성

```bash
conda activate ringserver_seedlink_websocket
python scripts/build_plan_html.py
```
