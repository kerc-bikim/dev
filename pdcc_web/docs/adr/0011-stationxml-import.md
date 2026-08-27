# ADR 0011. StationXML 가져오기와 원본 FileAsset

상태: 채택  
코드: `apps/api/app/inventory/importers.py`, `apps/web/src/editor/ProjectHome.tsx`

## 결정

1. `POST /api/projects/import` 가 UTF-8 StationXML 1.2 만 연다. 깨진 XML·다른 루트·schemaVersion 불일치는 `XSD` 로 거부한다.
2. 원문 바이트는 `file_assets` (`kind=original`) 에 두고 편집 XML 과 덮어쓰지 않는다. `GET /api/projects/{id}/original` 로 받는다.
3. zip·dataless SEED 는 이 티켓에서 거부하고 안내만 한다. 네트워크가 여러 개면 거부한다.

통과 시나리오: **S2** 의 StationXML 경로 (SEED 제외).
