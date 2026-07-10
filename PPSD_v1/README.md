# PPSD Web Viewer

FDSNWS 서버(기본: `http://172.31.100.100`)로부터 파형과 계측기 응답을 받아
ObsPy 로 확률 밀도 함수(PPSD)를 계산하고, IRIS MUSTANG 스타일의 히트맵을
사용자 지정 percentile 오버레이/클리핑과 함께 웹에서 조회하는 도구입니다.

## 구성

- `backend/` – FastAPI + ObsPy (`obspy.signal.PPSD`)
- `frontend/` – React + Vite + TypeScript
- `docker-compose.yml` – 두 서비스 원클릭 실행

## 로컬 개발

### 1. 백엔드

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# FDSNWS 주소를 바꾸고 싶으면
copy .env.example .env
# .env 내용을 편집

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API 문서: `http://localhost:8000/docs`

### 2. 프론트엔드

```powershell
cd frontend
npm install
npm run dev
```

브라우저에서 `http://localhost:5173` 열기. dev 서버는 `/api/*` 요청을
`http://localhost:8000` 으로 프록시합니다.

## Docker 로 실행

```powershell
# 필요하면 FDSNWS 주소 재정의
$env:FDSNWS_URL = "http://172.31.100.100"

docker compose up --build
```

- 프론트엔드: `http://localhost:8080`
- 백엔드 API: `http://localhost:8000/api`

컨테이너에서 `172.31.100.100` 에 접근 가능해야 합니다. 사내망 접근이
필요한 경우 host 네트워크(`network_mode: host`) 로 전환하거나 라우팅을 확인하세요.

## API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/api/health` | 상태와 현재 FDSNWS URL |
| GET | `/api/plot-defaults` | `.env` 에 설정된 축 범위 기본값 |
| GET | `/api/networks` | 네트워크 목록 |
| GET | `/api/stations?network=` | 스테이션 목록 |
| GET | `/api/channels?network=&station=` | 채널 목록 |
| POST | `/api/ppsd` | PPSD 계산 → `{job_id, image_url, stats}` |
| GET | `/api/ppsd/{job_id}/{plot_key}.png` | 렌더된 이미지 |
| POST | `/api/ppsd/batch` | 다중 target PPSD 병렬 계산 → 그리드용 결과 목록 |
| POST | `/api/ppsd/compare` | 다중 target percentile 곡선 비교 PNG |
| GET | `/api/ppsd/compare/{render_key}.png` | 비교 렌더 이미지 |

### UI 탭

- **Single** – 단일 관측소/채널 PPSD 히트맵
- **Multi** – 여러 관측소/채널을 동시에 계산하여 2열 그리드로 표시
- **Compare Station** – 동일 시간 구간에서 여러 관측소의 percentile 곡선을 한 그래프에 오버레이 (관측소별 색상, percentile별 선 스타일)
- **Compare Time** – 동일 관측소·채널에서 서로 다른 시간 구간의 percentile 곡선을 한 그래프에 오버레이 (시간대별 색상, percentile별 선 스타일)

### 단일 요청 예시

`POST /api/ppsd` 요청 예시:

```json
{
  "network": "IU",
  "station": "ANMO",
  "location": "00",
  "channel": "BHZ",
  "starttime": "2024-01-01T00:00:00Z",
  "endtime":   "2024-01-02T00:00:00Z",
  "percentile_low": 10,
  "percentile_high": 90,
  "show_overlay": true,
  "clip_to_percentile": false,
  "xaxis": "period",
  "show_noise_models": true,
  "show_mean": false,
  "show_mode": false,
  "cmap": "viridis"
}
```

### 배치 요청 예시

`POST /api/ppsd/batch`:

```json
{
  "targets": [
    {"network": "IU", "station": "ANMO", "location": "00", "channel": "BHZ"},
    {"network": "IU", "station": "COLA", "location": "00", "channel": "BHZ"}
  ],
  "starttime": "2024-01-01T00:00:00Z",
  "endtime": "2024-01-02T00:00:00Z",
  "options": {
    "percentile_low": 10,
    "percentile_high": 90,
    "show_overlay": true,
    "clip_to_percentile": false,
    "xaxis": "period",
    "show_noise_models": true,
    "cmap": "viridis"
  }
}
```

### 비교 요청 예시

`POST /api/ppsd/compare`:

```json
{
  "targets": [
    {"network": "IU", "station": "ANMO", "location": "00", "channel": "BHZ", "color": "#e74c3c"},
    {"network": "IU", "station": "COLA", "location": "00", "channel": "BHZ", "color": "#3498db"}
  ],
  "starttime": "2024-01-01T00:00:00Z",
  "endtime": "2024-01-02T00:00:00Z",
  "percentiles": [10, 50, 90],
  "xaxis": "period",
  "show_noise_models": true
}
```

## 병렬 계산

- `MAX_WORKERS` 환경변수로 ThreadPool 크기 조절 (기본 4).
- 요청당 최대 `MAX_TARGETS` 개 target (기본 20).
- 동일 target+시간 조합은 npz 캐시를 공유하여 Single/Multi/Compare Station/Compare Time 간 재사용.

## 축 범위 (X / Y)

UI의 **Axis range** 섹션 또는 API 요청의 `x_min`, `x_max`, `y_min`, `y_max` 로 지정합니다.

- X축 단위는 `xaxis` 에 따라 **period [s]** 또는 **frequency [Hz]**
- Y축 단위는 **dB** (PSD). UI 드롭다운 라벨 예: `PSD [dB rel. (m/s²)²/Hz]`
- Y축 물리량 타입: `acceleration` (기본), `velocity`, `velocity_nm`, `displacement`, `pressure`
- 우선순위: **요청 값** → **`.env` 기본값** → **단위별 기본 범위** → **데이터 자동 범위**

단위별 Y축 기본 범위 [dB] (요청·`.env` 미지정 시):

| 타입 | Y축 라벨 | 기본 Y 범위 |
| --- | --- | --- |
| `displacement` | PSD [dB rel. m²/Hz] | -120 ~ 40 |
| `velocity` | PSD [dB rel. (m/s)²/Hz] | -220 ~ -40 |
| `velocity_nm` | PSD [dB rel. (nm/s)²/Hz] | -40 ~ 140 |
| `acceleration` | PSD [dB rel. (m/s²)²/Hz] | -210 ~ -30 |
| `pressure` | PSD [dB rel. Pa²/Hz] | -20 ~ 100 |

UI에서 Y축 단위를 바꾸면 위 기본 범위로 Y축 min/max가 자동 갱신됩니다.

`backend/.env` 예시:

```env
PPSD_X_MIN=0.1
PPSD_X_MAX=100
PPSD_Y_MIN=-200
PPSD_Y_MAX=-50
PPSD_YAXIS_TYPE=acceleration
```

`PPSD_YAXIS_TYPE`: `acceleration` | `velocity` | `velocity_nm` | `displacement` | `pressure`

압력 PSD(`pressure`)는 센서/채널에 따라 가속도 PSD와 직접 환산되지 않을 수 있습니다. 필요 시 `.env`의 `PPSD_PRESSURE_DB_OFFSET`(dB)으로 표시 스케일을 보정하세요.

프론트엔드는 시작 시 `GET /api/plot-defaults` 로 위 값을 불러와 입력란에 채웁니다.
비워두면 서버 `.env` 기본값(있을 경우) 또는 자동 범위를 사용합니다.

## IRIS MUSTANG 대비 지원 기능

| MUSTANG PDF 페이지 옵션 | 본 도구 지원 |
| --- | --- |
| Time window 선택 | O (`starttime`, `endtime`) |
| Percentile overlay | O (`percentile_low`, `percentile_high`, `show_overlay`) |
| Percentile 범위 밖 클리핑 | O (`clip_to_percentile`) |
| NLNM / NHNM 오버레이 | O (`show_noise_models`) |
| Period ↔ Frequency X축 전환 | O (`xaxis`) |
| Mode / Mean 곡선 | O (`show_mode`, `show_mean`) |
| Colormap 선택 | O (`cmap`) |
| 결과 PNG 다운로드 | O |
| 결과 캐싱 (동일 파라미터 재계산 스킵) | O (ObsPy `PPSD.save_npz`) |
| 다중 관측소/채널 동시 계산 | O (Multi 탭, `/api/ppsd/batch`) |
| 관측소 간 percentile 비교 (동일 시간) | O (Compare Station 탭, `/api/ppsd/compare`) |
| 시간대 간 percentile 비교 (동일 관측소) | O (Compare Time 탭, `/api/ppsd/compare-time`) |
| 병렬 계산 | O (`ThreadPoolExecutor`, `MAX_WORKERS`) |
| X/Y 축 범위 지정 | O (UI + API + `.env` 기본값) |
| Y축 단위 (가속도/속도/nm/s/변위/압력 PSD) | O (`yaxis_type`) |

## 캐싱

- 데이터 파라미터(net/sta/loc/cha/시작/종료) 해시로 PPSD 를
  `backend/cache/<hash>.npz` 에 저장합니다.
- 플로팅 옵션(퍼센타일/컬러맵/축 등) 해시로 PNG 를
  `backend/cache/<hash>_<plot_key>.png` 로 저장/재사용.
- 같은 계산을 반복 요청하면 초 단위로 응답이 돌아옵니다. Docker 사용 시
  `ppsd-cache` 볼륨을 통해 재시작 후에도 유지됩니다.

## 트러블슈팅

### `ModuleNotFoundError: No module named 'pkg_resources'`

Python 3.12+ 환경에서 발생할 수 있습니다. ObsPy 1.4.x 는 아직 내부적으로
`pkg_resources` (setuptools 의 서브모듈) 를 사용하는데, 최신 pip/venv/conda 는
`setuptools` 를 자동 설치하지 않습니다.

해결:

```powershell
conda activate PPSD
python -m pip install "setuptools>=68,<81" setuptools-scm
```

`setuptools 81` 부터 `pkg_resources` 가 제거되었으므로 상한을 두는 것이 안전합니다.

## 참고

- ObsPy PPSD 문서: <https://docs.obspy.org/packages/autogen/obspy.signal.spectral_estimation.PPSD.html>
- IRIS MUSTANG PDF metric: <http://service.iris.edu/mustang/noise-pdf/1/>
- Peterson (1993) NLNM/NHNM
