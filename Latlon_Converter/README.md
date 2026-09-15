# Latlon_Converter — 좌표로 지번·토지정보 조회

위도/경도를 넣으면 그 좌표가 속한 **필지의 지번과 토지 정보**를 알려 주는 CLI 도구입니다.
관측소 좌표 목록(CSV)을 한 번에 처리해 지번을 채워 넣는 용도로 만들었습니다.

- 상태: CLI(단건·일괄·PNU 조회) 구현 완료, 웹 UI는 후속 과제
- 스택: Python 3.12 + requests (외부 의존성 이것 하나), 표준 라이브러리 sqlite 캐시
- 자료 출처: 브이월드(국토교통부 공간정보 오픈플랫폼) 오픈API
- UI: 한국어

---

## 먼저 알아 둘 것 — 토지주 실명은 API로 받을 수 없습니다

토지 소유자의 **성명과 주소는 어떤 공개 API로도 제공되지 않습니다.** 개인정보이기 때문입니다.
국토교통부 토지소유정보(브이월드 `ned/data/ladfrlList`)가 주는 소유 관련 항목은 다음까지입니다.

- 소유구분: 개인 / 국유지 / 시·도유지 / 군유지 / 법인 / 종중 / 종교단체 / 외국인 / 기타단체
- 공유인수(공동소유자 수)
- 소유권 변동 원인과 변동 일자

이 도구는 위 항목을 모두 보여 주고, 실명이 필요한 경우 **등기사항증명서**(인터넷등기소
<https://www.iros.go.kr/>)에서 지번으로 열람하도록 안내합니다. 결과의 `등기열람URL` 컬럼이
그 링크입니다.

---

## 구성

```
Latlon_Converter/
├── latlon_converter/
│   ├── cli.py            argparse 진입점 (point / batch / pnu)
│   ├── service.py        조회 오케스트레이션, 기준연도 폴백, 부분 실패 처리
│   ├── providers/
│   │   ├── base.py       제공자 프로토콜 (좌표→필지, PNU→대장/특성)
│   │   ├── vworld.py     브이월드 실 API 호출 + 재시도
│   │   └── mock.py       fixtures 재생 + 결정론적 합성 (키 없이 동작)
│   ├── parsers.py        응답 파싱 (mock과 실 API가 공유)
│   ├── pnu.py            PNU 19자리 조립·해석, 산 번지 처리
│   ├── codes.py          지목·대장구분·소유구분 코드표
│   ├── cache.py          sqlite 응답 캐시 (일일 한도 절약)
│   ├── batch.py          CSV 일괄 조회, 좌표 컬럼 자동 인식
│   ├── report.py         표 / CSV / JSON 출력
│   ├── models.py         Parcel / LandLedger / LandCharacteristics / LookupResult
│   └── config.py         환경변수 · .env 로더
├── fixtures/             실제 응답 스키마 샘플 (mock + 파서 테스트가 공유)
├── examples/stations_sample.csv
└── tests/                pytest (네트워크 불필요)
```

---

## 빠른 시작 (키 없이)

기본 제공자는 `mock`이라 인증키 없이 바로 돌려 볼 수 있습니다. 모노레포 공용 가상환경을 씁니다.

```bash
cd /workspace/Latlon_Converter

# 단건 조회
../.venv/bin/python -m latlon_converter point --lat 37.50435 --lon 127.02505

# CSV 일괄 조회
../.venv/bin/python -m latlon_converter batch \
    --input examples/stations_sample.csv --output out/result.csv

# PNU로 직접 조회
../.venv/bin/python -m latlon_converter pnu --pnu 4215038023200120003
```

`mock`은 `fixtures/`에 등록된 좌표면 실제 스키마의 샘플 응답을 재생하고, 그 밖의 국내 좌표는
좌표 해시로 **합성 데이터**를 만들어 냅니다. 합성된 결과는 실제 지번으로 오해하지 않도록
이렇게 표시됩니다.

- 지번주소·법정동명이 `[모의] 가상시 가상구 가동`처럼 실재하지 않는 이름
- 법정동코드와 PNU가 실제로 쓰이지 않는 `9999…`로 시작
- `비고`에 합성 데이터라는 안내와 실제 조회 방법

즉, `[모의]`나 `9999`가 보이면 **그 좌표는 실제로 조회된 것이 아닙니다.** 실제 지번이 필요하면
아래처럼 인증키를 설정하고 `--provider vworld`로 실행해야 합니다.

---

## 브이월드 인증키 준비 (실제 조회)

1. <https://www.vworld.kr> 회원가입 후 `오픈API > 인증키 발급`으로 이동합니다.
2. **활용 API에서 다음 세 가지를 모두 체크**합니다. 하나라도 빠지면 해당 조회가 실패합니다.
   - 검색 API — 좌표→주소 폴백
   - 2D데이터 API — 연속지적도(필지·PNU·공시지가)
   - 국가중점데이터 API — 토지임야정보, 토지특성정보
3. 서비스 유형을 웹사이트로 하면 **서비스 URL**을 등록하게 되는데, 이 값을 `VWORLD_DOMAIN`과
   **똑같이** 맞춰야 합니다. 2D데이터·국가중점 API는 `domain` 파라미터가 없거나 다르면
   `INCORRECT_KEY` 오류가 납니다.
4. `.env.example`을 `.env`로 복사해 키를 채웁니다.

```bash
cp .env.example .env
# VWORLD_API_KEY=..., VWORLD_DOMAIN=http://localhost, LATLON_PROVIDER=vworld

../.venv/bin/python -m latlon_converter point --lat 37.50435 --lon 127.02505 --provider vworld
```

### 환경변수

- `VWORLD_API_KEY` — 브이월드 인증키
- `VWORLD_DOMAIN` — 인증키에 등록한 서비스 URL
- `LATLON_PROVIDER` — `mock`(기본) 또는 `vworld`
- `LATLON_CACHE_DB` — 응답 캐시 sqlite 경로 (비우면 캐시 안 함)
- `LATLON_CACHE_TTL_DAYS` — 캐시 유효기간, 기본 30일
- `LATLON_TIMEOUT` / `LATLON_RETRIES` — HTTP 타임아웃(초)과 재시도 횟수

---

## 명령

### `point` — 좌표 한 건

```
--lat / --lon     WGS84 위도·경도 (필수)
--with-road       도로명주소도 함께 조회
--json / --csv    출력 형식 (기본은 사람이 읽는 표)
```

### `batch` — CSV 일괄

```
--input           입력 CSV (필수)
--output          출력 CSV (생략 시 표준출력)
--lat-col/--lon-col  좌표 컬럼명 (생략 시 위도/경도/latitude/longitude/lat/lon 자동 인식)
--sleep           요청 간격(초), 기본 0.2
--limit           상위 N행만 처리
```

입력 CSV의 나머지 컬럼(관측소코드 등)은 결과 앞쪽에 그대로 실려 나오므로 원본과 대조하기 쉽습니다.
한 행이 실패해도 `비고`에 `[오류]`로 남기고 다음 행을 계속 처리합니다.

**인코딩**: 입력은 UTF-8로 읽으며 BOM이 있어도 그대로 처리합니다. 출력은 **UTF-8 BOM**으로 쓰기
때문에 엑셀에서 바로 열어도 한글이 깨지지 않습니다. 한국어 윈도우 엑셀은 BOM이 없으면 CP949로
해석해 `愿�痢≪냼肄붾뱶`처럼 깨뜨리므로, 직접 만드는 입력 CSV도 UTF-8 BOM으로 저장하는 편이
안전합니다. 동봉한 [`examples/stations_sample.csv`](examples/stations_sample.csv)가 그렇게
저장되어 있습니다.

### `pnu` — PNU로 직접

```
--pnu             19자리 PNU
```

### 공통 옵션

```
--provider mock|vworld   제공자 지정 (기본은 LATLON_PROVIDER)
--year                   토지특성 기준연도 (생략 시 올해부터 2년 전까지 역순 탐색)
--no-cache               캐시 우회
-v                       디버그 로그
```

### 종료코드

- `0` 성공 (필지를 못 찾은 경우도 포함)
- `1` 입력 오류
- `2` 인증/설정 오류 (키 없음, 키·도메인 불일치)
- `3` 일일 호출 한도 초과
- `4` 네트워크 실패

---

## 출력 항목

입력위도, 입력경도, 지번주소, 도로명주소, PNU, 법정동코드, 법정동명, 대장구분, 지목, 면적(㎡),
소유구분, 공유인수, 소유권변동원인, 소유권변동일자, 개별공시지가(원/㎡), 공시기준연도,
용도지역1, 용도지역2, 토지이용상황, 등기열람URL, 비고.

**PNU**는 필지 고유번호 19자리로 `법정동코드(10) + 대장구분(1) + 본번(4) + 부번(4)` 구조입니다.
대장구분은 토지대장이 `1`, 임야대장(산 번지)이 `2`입니다.

---

## 조회 방식과 호출 수

좌표 한 건당 브이월드 호출은 2~3회입니다.

1. `req/data` 연속지적도(`LP_PA_CBND_BUBUN`)를 좌표로 질의 — PNU, 지번, 주소, 공시지가를 한 번에 받습니다.
   필지가 안 잡히면 `req/address` 지오코더로 한 번 더 시도해 법정동코드와 지번으로 PNU를 조립합니다.
2. `ned/data/ladfrlList` — 지목, 면적, 대장구분, 소유구분, 공유인수
3. `ned/data/getLandCharacteristics` — 용도지역, 토지이용상황, 공시지가

2·3번이 실패해도 1번 결과는 살려서 돌려주고 실패 사유를 `비고`에 남깁니다. 인증 오류와 한도
초과만 즉시 중단합니다. 같은 요청은 sqlite 캐시에서 재사용하므로 일괄 재실행이 한도를
축내지 않습니다.

---

## 테스트

```bash
cd /workspace/Latlon_Converter
../.venv/bin/python -m pytest -q
```

네트워크 없이 돕니다. `fixtures/`의 샘플 응답을 mock 제공자와 파서 테스트가 함께 쓰기 때문에,
실제 응답 스키마가 바뀌면 두 경로가 같이 깨져 바로 드러납니다.

---

## 한계와 후속 과제

- 소유자 실명·주소는 제공 불가 (위 안내 참고)
- 연속지적도는 연속지적(수치지적) 기준이라 경계 정밀도가 지적도 원본과 다를 수 있습니다.
- 도로명주소는 지오코더를 한 번 더 부르므로 `--with-road`를 켤 때만 조회합니다.
- 후속: FastAPI + React 웹 UI(지도 클릭 조회), `stationxml_manager` 관측소 좌표 직접 연계,
  국유지 판정 시 관리청 조회.
