# 0004. `-B` pack 실패 시 원본을 섞지 않는다

* 상태: Accepted
* 날짜: 2026-08
* 관련: `local_pack_fail_is_fatal()`, `local_discard_original()`, `local_encoding_can_pack()`

## 맥락

upstream은 trim할 수 없는 인코딩을 만나면 원본 레코드를 쓰고 경고합니다 (`trimrecord` 반환 -2). `-B`에 같은 fallback을 쓰면 한 파일에 512바이트 재패킹 레코드와 4096바이트 원본이 섞입니다. 다운스트림 고정 길이 리더가 깨집니다.

## 결정

`-B`가 있으면 다음을 **치명 오류(종료 1)** 로 처리하고 원본을 쓰지 않습니다.

* pack 불가 인코딩 (CDSN, int24 등)
* 헤더가 요청 블록보다 큼
* `msr3_parse` / `msr3_pack` 실패
* 일부 샘플만 pack됨 (`local_incomplete_pack`)

trim만 있고 `-B`가 없으면 기존처럼 원본 통과 + 경고를 유지합니다.

허용 인코딩: DE_TEXT, INT16, INT32, FLOAT32, FLOAT64, STEIM1, STEIM2.

## 결과

* 장점: `-B` 출력의 레코드 길이가 균일합니다 (v2는 항상 요청 길이).
* 단점: 레거시 인코딩 아카이브는 `-B`를 쓸 수 없습니다. 이미 몇 장을 쓴 뒤 실패하면 부분 파일이 남을 수 있습니다.
* 함의: 부분 쓰기 후 실패는 호출 측에서 출력을 폐기해야 합니다. 프로그램은 트랜잭션 출력을 하지 않습니다.
