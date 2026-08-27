# ADR 0005. RESP / dataless SEED 내보내기와 작업 큐

상태: 채택  
코드: `apps/api/app/export/`, `apps/api/app/jobs/`, `apps/worker/`, `apps/web/src/jobs/`, `apps/web/src/editor/ExportPanel.tsx`

## 맥락

IRIS PDCC는 dataless SEED와 RESP를 다룬다. PDCC Web의 진실은 StationXML 원문이다. ObsPy 1.5.0은 `Inventory.write(format="SEED")` / `format="RESP"` 가 없고, 큰 변환을 API 요청 스레드에서 돌리면 편집기가 멈춘다.

## 결정

1. **원문 보존.** 내보내기는 프로젝트 `xml_text`를 복사·슬라이스한 뒤 ObsPy Inventory를 **뷰**로만 쓴다. 저장 경로에 `Inventory.write()`를 넣지 않는다.
2. **dataless SEED.** 파형 MiniSEED/full SEED는 내보내지 않는다. ObsPy xseed `Parser` 블록ette로 메타데이터 볼륨만 만든다. 네트워크 코드 2자, 응답 없는 채널은 오류로 차단한다.
3. **RESP.** dataless를 만든 다음 `Parser.get_resp()`로 rdseed/evalresp 호환 텍스트를 만든다. 채널 하나면 `RESP.NET.STA.LOC.CHA`, 여러 채널이면 zip이다.
4. **변환 손실.** 70자 코멘트, 25자 FIR 이름, 60자 사이트명, 비 ASCII 사이트명 대체는 목록으로 보여 주고, `accept_losses=true` 없이는 409다. Operator 등 SEED에 없는 필드는 안내만 한다.
5. **작업 큐.** `export_jobs` 테이블 + Redis 리스트 `pdcc:jobs:queue` (LPUSH/BRPOP). API는 대기 상태를 바로 반환한다. 워커(`python -m app.jobs.runner`)가 변환하고 산출물을 `EXPORT_DIR`에 둔다. 같은 작업 id로 재시도하면 스냅샷 XML을 다시 쓴다.
6. **범위.** 프로젝트 / 관측소 epoch / 채널. UI는 미리보기·작업 벨·받기를 제공한다.

## 이번에 넣지 않은 것

SEED/RESP 가져오기, 공식 StationXML validator sidecar, `_unvalidated` XML, 관측소 복제 표, 대량 검증. 운영 compose·인증 강화는 M4.

## 결과

위저드로 만든 관측소에서 RESP와 dataless SEED를 받아 평가·배포 파이프라인에 넘길 수 있다. 편집 원문은 바뀌지 않는다.
