# StationXML 메타데이터 관리

엑셀 또는 StationXML을 올려 관측소/채널 메타데이터를 고치고, 다시 StationXML·엑셀로 내보내는 로컬 웹 도구입니다. 센서와 기록계는 카탈로그 ID만 고를 수 있습니다.

## 구성

- `app/` — FastAPI + ObsPy + SQLite
- `frontend/` — React + Vite (한글 UI)
- `equipment_catalog.yaml` — 최초 장비 목록(이후는 DB가 원본)

SQLite 파일은 `data/stationxml.db`에 저장됩니다.

## 웹으로 실행

```bash
cd stationxml_manager
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 백엔드
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 프론트엔드 (다른 터미널)
cd frontend
npm install
npm run dev
```

브라우저에서 `http://localhost:5173`을 엽니다. API 문서: `http://localhost:8000/docs`.

프론트를 빌드해 백엔드와 같이 쓰려면:

```bash
cd frontend && npm install && npm run build
cd ..
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## CLI

```bash
# 드롭다운이 있는 엑셀 템플릿
python -m app.cli --write-template stations.xlsx

# 엑셀 또는 StationXML → DB 적재 후 StationXML 저장
python -m app.cli stations.xlsx -o inventory.xml
python -m app.cli inventory.xml -o inventory.xml --replace-all
```

NRL 응답은보내기 때 자동으로 붙지 않습니다. 웹의 **NRL** 버튼 또는 `--apply-nrl`일 때만 적용합니다.

## 엑셀 사용

한 행 = 한 채널입니다. 같은 관측소의 사이트명·좌표 등이 행마다 다르면 가져오기가 실패합니다.

**필수 열:** 네트워크, 관측소, 채널, 위도, 경도, 시작시간, 샘플링레이트

센서ID·기록계ID는 `catalog_sensors` / `catalog_dataloggers` 시트 값만 쓸 수 있습니다. 알 수 없는 열 이름은 거절됩니다.

### 엑셀 왕복 한계

계측기 응답(Response)은 StationXML에만 있습니다. 엑셀은 표 메타데이터용입니다. StationXML을 올린 뒤 엑셀을 다시 가져와도 기존 응답은 유지됩니다.

## 값 검사

- 위도 -90~90, 경도 -180~180
- 시작시간 < 끝시간
- 고도 0이면 경고(저장은 허용)
- 기록계 카탈로그 sps와 채널 샘플링레이트 일치
- 채널이 쓰는 장비 ID는 카탈로그에서 삭제 불가

## 테스트

```bash
cd stationxml_manager
PYTHONPATH=. pytest -q
```
