# Latlon_Converter — 좌표로 지번·토지정보 조회

위도/경도를 넣으면 그 좌표가 속한 **필지의 지번과 공개 토지 정보**를 알려 주는 CLI입니다.
관측소 좌표 CSV를 한 번에 처리해 지번·소유구분·공시지가를 채우는 용도로 만들었습니다.

- 상태: CLI(단건·일괄·PNU·주소검색·연결점검) 구현 완료. 웹 UI는 후속
- 스택: Python 3.12 + `requests`, 표준 라이브러리 sqlite 캐시
- 자료: 브이월드(국토교통부 공간정보 오픈플랫폼) 오픈API
- 실행 예: conda 환경 `Latlon_converter`에서 `python -m latlon_converter`

```powershell
cd C:\Users\bikim\dev-git\Latlon_Converter
conda activate Latlon_converter
python -m latlon_converter -h
```

---

## 이 도구가 하는 일

| 되는 것 | 안 되는 것 |
| --- | --- |
| 좌표 → 지번주소, PNU, 지목, 면적, 대장구분 | 소유자 **성명·주소** (공개 API 미제공) |
| 소유구분 (개인/국유지/군유지/법인 등) | 어느 부처·누구 명의인지까지 |
| 국유지의 국가기관구분 (중앙부처, 지자체 등) | 등기부 갑구의 권리 관계 |
| 개인의 거주지구분 (시도내, 시도외 등) | |
| 공유인수, 소유권변동원인·일자 | |
| 개별공시지가, 용도지역, 토지이용상황 | |
| GPS(WGS84)와 구 지적(동경측지계) 혼용 | |
| 주변 필지, 지번 주소로 좌표 검색 | |

실명이 필요하면 결과의 `등기열람URL`(인터넷등기소 <https://www.iros.go.kr/>)에서 지번으로 등기사항증명서를 열람하세요.

소유 세부는 토지임야정보(`ladfrlList`)의 소유구분에, 토지소유정보(`getPossessionAttr`)의 국가기관구분·거주지구분을 붙여 보여 줍니다. `구분없음` 같은 자리채움은 비웁니다.

---

## 알아 둘 것 — 좌표계

연속지적도는 **WGS84** 기준입니다. GPS·스마트폰 좌표는 `--crs wgs84`(기본)로 조회하면 됩니다.

구 지적 성과·일부 관측소 성과는 **동경측지계(Bessel)** 인 경우가 있습니다. 그대로 넣으면 경도가 약 10.405″(한반도에서 대략 200~300m) 서쪽으로 어긋나, 옆 필지(예: 산 번지)가 잡힙니다.

| 입력 | 쓰는 옵션 | 예 |
| --- | --- | --- |
| GPS, 구글맵, 스마트폰 | `--crs wgs84` (기본) | 역삼동 808 |
| 구 지적, 동경측지계 관측소 | `--crs tokyo` | 백령 가을리 853 (`37.968352, 124.645289`) |

한 CSV에 두 종류가 섞여 있으면 `좌표계` 컬럼을 넣습니다. 값은 `wgs84` / `tokyo` (동의어: `gps`, `동경`, `bessel` 등). 비우면 `--crs` 기본값을 씁니다.

`--crs wgs84` 결과는 지적 경계상 맞는 필지입니다. 기대 지번과 200~300m가량 어긋나면 `--crs tokyo`로 한 번 더 보세요.

---

## 빠른 시작 (키 없이)

기본 제공자는 `mock`이라 인증키 없이 바로 돌려 볼 수 있습니다.

```powershell
cd C:\Users\bikim\dev-git\Latlon_Converter
conda activate Latlon_converter

python -m latlon_converter point --lat 37.50435 --lon 127.02505
python -m latlon_converter batch --input examples/stations_sample.csv --output out/result.csv
python -m latlon_converter pnu --pnu 4215038023200120003
```

`mock`은 `fixtures/`에 등록된 좌표면 실제 스키마의 샘플을 재생하고, 그 밖의 국내 좌표는 해시로 **합성 데이터**를 만듭니다. 합성 결과는 실제 지번이 아닙니다.

- 주소·법정동명이 `[모의] 가상시 가상구 가동`처럼 실재하지 않는 이름
- 법정동코드·PNU가 `9999…`로 시작
- `비고`에 합성 데이터라는 안내

`[모의]`나 `9999`가 보이면 그 좌표는 실제로 조회된 것이 아닙니다. 실제 지번은 인증키를 넣고 `--provider vworld`로 실행하세요.

---

## 브이월드 인증키 (실제 조회)

1. <https://www.vworld.kr> 회원가입 후 `오픈API > 인증키 발급`
2. **활용 API에서 다음을 모두 체크**합니다. 빠지면 해당 조회가 실패합니다.
   - 검색 API — 좌표→주소 폴백, `search` 명령
   - 2D데이터 API — 연속지적도(필지·PNU·공시지가)
   - 국가중점데이터 API — 토지임야정보, 토지소유정보, 토지특성정보
3. 서비스 유형이 웹사이트면 **서비스 URL**을 `VWORLD_DOMAIN`과 **똑같이** 맞춥니다. 다르면 `INCORRECT_KEY`가 납니다.
4. `.env.example`을 `.env`로 복사해 키를 채웁니다. `.env`는 커밋하지 마세요.

```powershell
copy .env.example .env
# VWORLD_API_KEY, VWORLD_DOMAIN 을 채운 뒤
# LATLON_PROVIDER=vworld  또는  명령줄 --provider vworld

python -m latlon_converter point --lat 37.50435 --lon 127.02505 --provider vworld
python -m latlon_converter point --lat 37.968352 --lon 124.645289 --crs tokyo --provider vworld
python -m latlon_converter check
```

### 환경변수

| 변수 | 역할 |
| --- | --- |
| `VWORLD_API_KEY` | 브이월드 인증키 |
| `VWORLD_DOMAIN` | 인증키에 등록한 서비스 URL |
| `LATLON_PROVIDER` | `mock`(기본) 또는 `vworld`. `--provider`가 우선 |
| `LATLON_CA_BUNDLE` | 사내망 TLS 검사용 PEM 인증서 경로 |
| `LATLON_CACHE_DB` | 응답 캐시 sqlite 경로. 비우면 캐시 안 함 |
| `LATLON_CACHE_TTL_DAYS` | 캐시 유효기간, 기본 30일 |
| `LATLON_TIMEOUT` / `LATLON_RETRIES` | HTTP 타임아웃(초)·재시도 횟수 |

자세한 주석은 [`.env.example`](.env.example)에 있습니다.

### 사내망 인증서 (`CERTIFICATE_VERIFY_FAILED`)

사내 TLS 검사 장비를 거치면 기본 신뢰 저장소로 검증이 실패합니다. 보안팀에서 받은 인증서를 PEM으로 두고 `.env`에 경로를 적습니다.

```
LATLON_CA_BUNDLE=C:\certs\test.pem
```

- **PEM**이어야 합니다. `.crt`라도 DER(바이너리)인 경우가 많습니다. 변환: `openssl x509 -inform der -in test.crt -out test.pem`
- 인증서가 여러 장이면 루트·중간 PEM을 한 파일에 이어 붙입니다.
- 상대경로는 실행 위치를 먼저 찾고, 없으면 `Latlon_Converter/`에서 찾습니다.
- `REQUESTS_CA_BUNDLE`도 인식하지만, 둘 다 있으면 `LATLON_CA_BUNDLE`이 우선합니다.
- 인증서 실패는 재시도하지 않고 종료코드 `5`로 끝납니다.
- `check`는 키가 없어도 인증서 검증 여부를 확인할 수 있습니다. 서버가 키 오류를 주는 것 자체가 TLS 성공입니다.

---

## 명령과 옵션

`python -m latlon_converter -h` 에 같은 목록이 나옵니다. 명령별 상세는 `python -m latlon_converter <명령> -h` 입니다.

### 공통

```
--provider mock|vworld   제공자. 기본은 LATLON_PROVIDER, 없으면 mock
--crs wgs84|tokyo        입력 좌표 기준. GPS는 wgs84, 구 지적은 tokyo
--year YEAR              토지특성 기준연도. 생략 시 올해부터 역순 탐색
--no-cache               응답 캐시 우회
-v / -vv                 로그. -v 조회 과정, -vv 요청·파라미터 상세
-h, --help               도움말
--version                버전
```

### `point` — 좌표 한 건

```
--lat / --lon            위도·경도 (필수)
--nearby [M]             주변 필지 (미터). 값 생략 시 300
--with-road              도로명주소 (지오코더 추가 호출)
--json / --csv           출력 형식. 기본은 표
```

```powershell
python -m latlon_converter point --lat 37.50435 --lon 127.02505
python -m latlon_converter point --lat 37.968352 --lon 124.645289 --crs tokyo --provider vworld -v
python -m latlon_converter point --lat 37.968352 --lon 124.645289 --nearby 300 --provider vworld
```

### `batch` — CSV 일괄

```
--input PATH             입력 CSV (필수)
--output PATH            출력 CSV. 생략 시 표준출력, UTF-8 BOM
--lat-col / --lon-col    좌표 컬럼명. 생략 시 위도/경도/latitude/lat 등
--crs-col NAME           행별 좌표계 컬럼. 생략 시 좌표계/crs/datum
--with-road              도로명주소
--sleep SEC              요청 간격(초). 기본 0.2
--limit N                상위 N행만
```

```csv
관측소코드,위도,경도,좌표계
BRD01,37.968352,124.645289,tokyo
YPD00,37.67535,125.71027,wgs84
```

```powershell
python -m latlon_converter batch --input examples/stations_sample.csv --output out/result.csv --provider vworld
```

입력의 나머지 컬럼(관측소코드 등)은 결과 앞에 그대로 붙습니다. 한 행이 실패해도 `비고`에 `[오류]`로 남기고 다음 행을 계속 처리합니다.

**인코딩**: 입력은 UTF-8(BOM 있어도 됨). 출력은 **UTF-8 BOM**이라 엑셀에서 한글이 깨지지 않습니다. 한국어 윈도우 엑셀은 BOM이 없으면 CP949로 읽어 깨지므로, 입력 CSV도 UTF-8 BOM으로 저장하는 편이 안전합니다. [`examples/stations_sample.csv`](examples/stations_sample.csv)가 그 형식입니다.

### `pnu` — 필지고유번호

```
--pnu PNU                19자리 (필수)
--json / --csv
```

```powershell
python -m latlon_converter pnu --pnu 2872033023108530000 --provider vworld
```

### `search` — 지번 주소로 좌표

기대 지번의 위치를 연속지적도 결과와 대조할 때 씁니다.

```
--query TEXT             지번 주소 (필수)
--lat / --lon            있으면 그 점과의 거리도 표시
--json
```

```powershell
python -m latlon_converter search --query "인천광역시 옹진군 백령면 가을리 853" --provider vworld
```

### `check` — 인증서·인증키 점검

조회는 하지 않습니다. 인증서 실패 / 연결 실패 / 키 오류를 구분해 알려 주며, 호출 한도에 거의 영향이 없습니다.

```powershell
python -m latlon_converter check
```

### 종료코드

| 코드 | 의미 |
| --- | --- |
| `0` | 성공 (필지를 못 찾은 경우도 포함) |
| `1` | 입력 오류 |
| `2` | 인증/설정 오류 (키 없음, 키·도메인 불일치, 인증서 경로·형식) |
| `3` | 일일 호출 한도 초과 |
| `4` | 네트워크 실패 |
| `5` | 서버 인증서 검증 실패 (`LATLON_CA_BUNDLE` 필요) |

---

## 출력 항목

입력위도, 입력경도, 지번주소, 도로명주소, PNU, 법정동코드, 법정동명, 대장구분, 지목, 면적(㎡),
소유구분, 국가기관구분, 거주지구분, 공유인수, 소유권변동원인, 소유권변동일자,
개별공시지가(원/㎡), 공시기준연도, 용도지역1, 용도지역2, 토지이용상황, 등기열람URL, 비고.

**PNU**는 필지 고유번호 19자리입니다. `법정동코드(10) + 대장구분(1) + 본번(4) + 부번(4)`.
대장구분은 토지대장 `1`, 임야대장(산 번지) `2`.

표 모드에서는 값이 있는 행만 보여 줍니다. 국유지는 `국가기관구분`, 개인은 `거주지구분`이 채워지는 경우가 많습니다.

---

## 조회 방식과 호출 수

좌표 한 건당 브이월드 호출은 3~4회입니다.

1. `req/data` 연속지적도(`LP_PA_CBND_BUBUN`) — PNU, 지번, 주소, 공시지가. 도형으로 점이 들어가는 필지 중 면적이 작은 것을 고릅니다. 안 잡히면 `req/address` 지오코더로 법정동코드·지번에서 PNU를 조립합니다. `--nearby`면 같은 API로 주변 BOX를 한 번 더 조회합니다.
2. `ned/data/ladfrlList` — 지목, 면적, 대장구분, 소유구분, 공유인수
3. `ned/data/getPossessionAttr` — 국가기관구분, 거주지구분, 소유권변동원인·일자
4. `ned/data/getLandCharacteristics` — 용도지역, 토지이용상황, 공시지가

2~4번이 실패해도 1번 결과는 남기고 `비고`에 사유를 적습니다. 인증 오류와 한도 초과만 즉시 중단합니다. 같은 요청은 sqlite 캐시에서 재사용합니다.

---

## 구성

```
Latlon_Converter/
├── latlon_converter/
│   ├── cli.py            argparse 진입점 (point / batch / pnu / search / check)
│   ├── service.py        조회 오케스트레이션, 기준연도 폴백, 동경측지계 변환
│   ├── providers/
│   │   ├── base.py       제공자 프로토콜
│   │   ├── vworld.py     브이월드 실 API + 재시도
│   │   └── mock.py       fixtures 재생 + 결정론적 합성
│   ├── parsers.py        응답 파싱 (mock과 실 API가 공유)
│   ├── geometry.py       점-폴리곤, 면적·거리
│   ├── datum.py          동경측지계(Bessel) → WGS84 (경도 +10.405″)
│   ├── pnu.py            PNU 19자리 조립·해석, 산 번지
│   ├── codes.py          지목·대장·소유·국가기관·거주지 코드표
│   ├── cache.py          sqlite 응답 캐시
│   ├── batch.py          CSV 일괄, 좌표·좌표계 컬럼 자동 인식
│   ├── report.py         표 / CSV / JSON
│   ├── models.py         Parcel / LandLedger / LookupResult
│   ├── logutil.py        -v / -vv, 인증키 마스킹
│   └── config.py         환경변수 · .env
├── fixtures/             실제 응답 스키마 샘플
├── examples/stations_sample.csv
├── .env.example
└── tests/
```

---

## 테스트

```powershell
cd C:\Users\bikim\dev-git\Latlon_Converter
conda activate Latlon_converter
python -m pytest -q --ignore=tests/test_tls.py
```

네트워크 없이 돕니다. `fixtures/`의 샘플을 mock과 파서 테스트가 같이 쓰므로, 실제 응답 스키마가 바뀌면 두 경로가 함께 깨집니다. `test_tls.py`는 실행 PC의 인증서 환경에 따라 달라져 기본 실행에서 빼 둡니다.

---

## 한계와 후속 과제

- 소유자 실명·주소, 구체적인 관리청 명칭은 제공하지 않습니다.
- 연속지적도는 수치지적 기준이라 경계 정밀도가 지적도 원본과 다를 수 있습니다.
- 도로명주소는 `--with-road`를 켠 때만 지오코더를 한 번 더 부릅니다.
- 후속: FastAPI + React 웹 UI(지도 클릭 조회), `stationxml_manager` 관측소 좌표 연계.
