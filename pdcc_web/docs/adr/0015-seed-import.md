# ADR 0015. dataless SEED 가져오기

상태: 채택  
코드: `apps/api/app/inventory/seed_convert.py`, `apps/api/app/inventory/importers.py`, `apps/web/src/editor/ProjectHome.tsx`

## 결정

1. `POST /api/projects/import-file` 이 StationXML과 dataless SEED를 받는다. 원문 바이트는 `file_assets(kind=original)` 에 두고 변환된 편집 XML과 덮어쓰지 않는다.
2. 변환은 `SEED_CONVERTER_JAR` 또는 `infra/jars/stationxml-seed-converter.jar` 가 있으면 공식 converter, 없으면 ObsPy `read_inventory(format="SEED")` → StationXML 1.2. 파형 MiniSEED·full SEED·zip은 거부한다. RESP는 M3-05(`docs/adr/0019-resp.md`).
3. 변환 경고(`W_SEED_CONVERT` 등)는 `file_assets(kind=import_warnings)` 에 저장하고 `GET /issues` · 검사 패널에 올린다.

통과 시나리오: **S2** (dataless SEED → 좌표 수정 → StationXML).
