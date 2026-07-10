# PPSD Web Viewer

FDSNWS 서버(기본: `http://172.31.100.100`)로부터 파형과 계측기 응답을 받아
ObsPy 로 확률 밀도 함수(PPSD)를 계산하고, IRIS MUSTANG 스타일의 히트맵을
사용자 지정 percentile 오버레이/클리핑과 함께 웹에서 조회하는 도구입니다.

## 구성

- `backend/` – FastAPI + ObsPy (`obspy.signal.PPSD`), 수치 데이터(JSON) 제공
- `frontend/` – React + Vite + TypeScript, **D3.js + WebGL** 로 차트 직접 렌더링
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
| POST | `/api/ppsd` | PPSD 계산 → `{job_id, data, stats}` (히트맵 수치 데이터) |
| POST | `/api/ppsd/batch` | 다중 target PPSD 병렬 계산 → 그리드용 결과 목록(각 `data`) |
| POST | `/api/ppsd/compare` | 동일 시간, 다중 관측소 percentile 곡선 비교 → `{data, items}` |
| POST | `/api/ppsd/compare-time` | 동일 관측소, 다중 시간창 percentile 곡선 비교 → `{data, items}` |

> 렌더링은 서버 PNG가 아니라 **프론트엔드에서 D3.js + WebGL로 직접** 그립니다.
> 백엔드는 히스토그램/곡선/축 등 수치 데이터(JSON)만 반환하고, 이미지 다운로드는
> 브라우저에서 캔버스를 PNG로 내보냅니다.

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
- 동일 관측소의 일자별 SDS npz 를 공유하여 Single/Multi/Compare Station/Compare Time 간 재사용.

## PPSD 결과 저장 (SeisComP SDS 구조)

PPSD 분석 결과는 **UTC 하루 단위**로 계산되어 SeisComP SDS 구조의 npz 로 저장되며,
이후 요청은 저장된 일자 파일을 재사용/병합(`PPSD.load_npz` + `add_npz`)합니다.

- 저장 위치: `PPSD_SDS_DIR` (기본 `backend/sds`)
- 경로 형식:
  `<SDS>/<YEAR>/<NET>/<STA>/<CHAN>.D/<NET>.<STA>.<LOC>.<CHAN>.D.<YEAR>.<JULDAY>.npz`
  - 예: `sds/2024/IU/ANMO/BHZ.D/IU.ANMO..BHZ.D.2024.001.npz`
- 부분 일(day) 요청도 교차하는 UTC 하루 전체를 계산/재사용하므로, 결과는 요청과
  겹치는 날짜들의 PPSD 통계입니다(IRIS/SeisComP 일 PPSD 관행과 동일).

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
# PPSD 결과 npz 저장 루트 (SeisComP SDS 구조)
PPSD_SDS_DIR=./sds
```

`PPSD_YAXIS_TYPE`: `acceleration` | `velocity` | `velocity_nm` | `displacement` | `pressure`

압력 PSD(`pressure`)는 센서/채널에 따라 가속도 PSD와 직접 환산되지 않을 수 있습니다. 필요 시 `.env`의 `PPSD_PRESSURE_DB_OFFSET`(dB)으로 표시 스케일을 보정하세요.

## 소음 모델 (Noise models)

`show_noise_models`가 켜져 있으면 참조 소음 모델을 함께 표기합니다.

- 지진계 단위(`acceleration`/`velocity`/`velocity_nm`/`displacement`): Peterson **NLNM/NHNM**
  (선택한 Y축 단위로 변환하여 표시)
- 음압(`pressure`): **IDC 전지구 인프라사운드 Low/High 소음 모델**
  (Brown et al. 2012, ObsPy 내장 `get_idc_infra_low_noise` / `get_idc_infra_hi_noise`,
  dB rel. Pa²/Hz, 변환 없이 표시)

> 인프라사운드 채널(SEED 계기코드 `D`: `BDF`, `HDF`, `LDF` 등)은 PPSD 계산 시
> `special_handling="infrasound"`로 처리되어 가속도로 미분하지 않고 압력 PSD를 그대로
> 산출합니다. 이런 채널은 Y축 단위가 자동으로 음압(`pressure`)으로 표시됩니다.

프론트엔드는 시작 시 `GET /api/plot-defaults` 로 위 값을 불러와 입력란에 채웁니다.
비워두면 서버 `.env` 기본값(있을 경우) 또는 자동 범위를 사용합니다.

## IRIS MUSTANG 대비 지원 기능

| MUSTANG PDF 페이지 옵션 | 본 도구 지원 |
| --- | --- |
| Time window 선택 | O (`starttime`, `endtime`) |
| Percentile overlay | O (`percentile_low`, `percentile_high`, `show_overlay`) |
| Percentile 범위 밖 클리핑 | O (`clip_to_percentile`) |
| NLNM / NHNM 오버레이 | O (`show_noise_models`, 음압은 IDC 인프라사운드 모델) |
| Period ↔ Frequency X축 전환 | O (`xaxis`) |
| Mode / Mean 곡선 | O (`show_mode`, `show_mean`) |
| Colormap 선택 | O (`cmap`) |
| 인터랙티브 렌더링 | O (프론트 D3.js + WebGL) |
| 결과 PNG 다운로드 | O (브라우저 캔버스 export) |
| 결과 캐싱 (동일 파라미터 재계산 스킵) | O (SeisComP SDS 일 단위 `PPSD.save_npz`) |
| 다중 관측소/채널 동시 계산 | O (Multi 탭, `/api/ppsd/batch`) |
| 관측소 간 percentile 비교 (동일 시간) | O (Compare Station 탭, `/api/ppsd/compare`) |
| 시간대 간 percentile 비교 (동일 관측소) | O (Compare Time 탭, `/api/ppsd/compare-time`) |
| 병렬 계산 | O (`ThreadPoolExecutor`, `MAX_WORKERS`) |
| X/Y 축 범위 지정 | O (UI + API + `.env` 기본값) |
| Y축 단위 (가속도/속도/nm/s/변위/압력 PSD) | O (`yaxis_type`) |

## 캐싱

- PPSD 는 **UTC 하루 단위**로 계산되어 SeisComP SDS 구조의 npz 로 저장됩니다
  (`PPSD_SDS_DIR`, 기본 `backend/sds`).
- 이후 요청은 해당 날짜의 npz 를 재사용/병합하므로 같은 날짜를 반복 계산하지 않습니다.
- 플로팅은 프론트엔드에서 수행하므로 서버 측 PNG 캐시는 없습니다.
- Docker 사용 시 SDS 디렉터리를 볼륨으로 마운트하면 재시작 후에도 유지됩니다.

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

## 프론트엔드 설정 (기본값)

상단 바의 **⚙ 설정** 버튼으로 기본값을 지정할 수 있습니다. 값은 브라우저
`localStorage`에 저장되어 새로고침/재접속 후에도 유지되며, 각 탭을 열 때 초기값으로
적용됩니다(탭 안에서 개별적으로 다시 변경 가능).

지정 가능한 기본값:

- Percentiles Low / High (Single·Multi)
- X 축 (Period / Frequency)
- Colormap
- Probability [%] 컬러바 범위 (기본 0–30)
- 오버레이/토글: Overlay percentile curves, Clip histogram to percentile range,
  Show Peterson NLNM/NHNM, Show mode curve, Show mean curve
- Compare 탭 기본 percentile 목록(예: `10, 50, 90`)

## 변경 이력 (Changelog)

형식은 [Keep a Changelog](https://keepachangelog.com/), 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

### [1.3.0] - 2026-07-10

**Added**

- 상단 바에 **설정(⚙) 메뉴** 추가. 프론트엔드 기본값을 브라우저 `localStorage`에
  저장하여 지속 적용합니다(각 탭 열 때 초기값으로 반영, 탭 내 개별 변경 가능).
  - 기본 Percentiles Low/High, 기본 X 축, 기본 Colormap
  - 토글 기본값: Overlay percentile curves, Clip histogram to percentile range,
    Show Peterson NLNM/NHNM, Show mode curve, Show mean curve
  - Compare 탭 기본 percentile 목록(예: `10, 50, 90`)
- 관련 파일: `settings/appSettings.ts`, `settings/SettingsContext.tsx`,
  `components/SettingsModal.tsx`.

### [1.2.3] - 2026-07-10

**Added**

- Plot options의 **Y axis 데이터 종류를 선택한 채널에 따라 자동 선택**. SEED 계기코드
  기준: `D`→음압(pressure), `N`→가속도(acceleration), `H`/`L`→속도(velocity).
  자동 선택 후에도 수동으로 다른 단위를 고를 수 있으며(수동 선택 유지),
  채널을 바꾸면 다시 채널에 맞는 단위로 갱신됩니다. Single/Multi/Compare Station/
  Compare Time 전 탭에 적용(여러 채널이 서로 다른 종류면 자동 변경하지 않음).

### [1.2.2] - 2026-07-10

**Fixed**

- Colormap 선택이 차트에 반영되지 않던 문제 수정. `turbo`/`hot`/`jet`이 프론트
  LUT(`colormap.ts`)에 정의돼 있지 않아 전부 viridis로 폴백되던 버그. `turbo`(d3 내장)
  추가, `hot`/`jet`은 직접 구현하여 선택한 컬러맵이 즉시 반영됩니다.

**Changed**

- 시간 선택 입력(datetime-local)을 오전/오후(12시간제)에서 **24시간제**로 변경
  (`lang="sv-SE"`, yyyy-mm-dd 형식 유지).

### [1.2.1] - 2026-07-10

인프라사운드(음압) 채널 PPSD 렌더링 오류 수정.

**Fixed**

- 인프라사운드 채널(`BDF`/`HDF`/`LDF` 등, SEED 계기코드 `D`)이 지진계로 처리되어
  응답 제거 시 가속도로 이중 미분되던 문제 수정. 해당 채널은
  `special_handling="infrasound"` + 압력용 `db_bins=(-120, 80, 1)`로 계산하여
  미분 없이 압력 PSD(dB rel. Pa²/Hz)를 산출합니다.
- 기본 `db_bins` 상단(-50 dB)에 값이 몰려 히트맵에 가짜 수평선이 그려지던 현상 제거.
- 컬러바가 확률[%]이 아닌 원시 카운트를 표시(0~5,000+)하던 버그 수정. 히스토그램을
  `count × 100 / 세그먼트수`로 정규화하고 컬러바 도메인을 `[0, vmax]`(%)로 변경.

**Changed**

- 음압 소음 모델을 손수 디지타이즈한 Bowman(2005) 근사치에서 ObsPy 내장
  **IDC 전지구 인프라사운드 Low/High 모델**(Brown et al. 2012)로 교체.
- 인프라사운드 채널은 Y축 단위를 자동으로 `pressure`로 표시(다른 단위 선택 시 축 범위도
  압력 기본값 적용).
- 음압 기본 Y축 표시 범위 `-20 ~ 100` → `-100 ~ 40 dB`(IDC 모델 범위에 맞춤).
- 구버전 처리 방식으로 저장된 SDS `.npz` 캐시는 `special_handling` 불일치를 감지해
  자동 재계산.

**Removed**

- 사용하지 않게 된 `backend/app/services/acoustic_noise_models.py`(Bowman 디지타이즈 표) 삭제.

### [1.2.0] - 2026-07-10

**Added**

- PPSD 분석 결과를 **SeisComP SDS 구조 `.npz`**로 UTC 일 단위 저장/재사용/병합
  (`PPSD_SDS_DIR`, `sds_store.py`).
- 프론트엔드 차트를 이미지(PNG)에서 **D3.js + WebGL** 인터랙티브 렌더링으로 전환.
  서버측 matplotlib PNG 생성 제거, 결과는 JSON 수치 데이터로 반환하고 PNG는
  브라우저 캔버스에서 export.

### [1.1.0] - 2026-07-09

**Added**

- **Compare 탭 분리**: 동일 시간·다른 관측소 비교(`Compare Station`)와
  동일 관측소·다른 시간대 비교(`Compare Time`, `/api/ppsd/compare-time`)로 구분.
- Y축 단위 선택 메뉴에 데이터 종류(변위/속도/가속도/음압) 함께 표기.

**Changed**

- Y축 라벨을 `PSD [dB rel. 단위]` 형식으로 정리, 단위별 기본 Y축 범위 지정
  (변위 -120~40, 속도 -220~-40, 가속도 -210~-30, 음압 -20~100 dB).

### [1.0.0] - 2026-07-08

**Added**

- 초기 릴리스: FDSNWS 파형·응답 조회, ObsPy PPSD 계산, IRIS MUSTANG 스타일 히트맵,
  percentile 오버레이/클리핑, 다중 관측소/채널 배치 계산, 축 범위 지정.
