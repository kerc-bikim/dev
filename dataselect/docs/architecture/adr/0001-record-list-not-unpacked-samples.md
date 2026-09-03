# 0001. 인덱스는 레코드 리스트, 샘플은 쓸 때 푼다

* 상태: Accepted
* 날짜: 2025 (upstream dataselect 설계, 이 포크가 유지)
* 관련: `MSF_RECORDLIST`, `writetraces()`, `trimrecord()`

## 맥락

입력은 파일·오프셋에 흩어진 miniSEED 레코드입니다. 프로그램은 채널별로 시간순 연속 구간을 재구성하고, overlap을 표시한 뒤, 기여하는 레코드만 출력해야 합니다. 모든 샘플을 처음부터 풀면 메모리와 시간이 커지고, 손대지 않을 레코드까지 재패킹하게 됩니다.

## 결정

libmseed `MS3TraceList`에 **레코드 포인터 리스트**를 둡니다 (`MSF_RECORDLIST`). 각 `MS3RecordPtr`는 파일 이름, 오프셋, 헤더(시각·인코딩·길이)를 가리킵니다. extra header는 리스트에 넣지 않습니다 (`MSF_RECORDLIST_NOEXTRAS`).

샘플은 `trimrecord()`가 필요할 때만 `msr3_parse(..., MSF_UNPACKDATA)`로 풉니다. 완전히 제거된 레코드는 `reclen = 0`으로 표시하고 바이트는 건드리지 않습니다.

## 결과

* 장점: 복사·레코드 단위 가지치기는 unpack 없이 원본 바이트를 씁니다. 수정이 필요한 레코드만 재패킹합니다.
* 단점: 쓰기는 입력 파일을 다시 seek/read 합니다. 열린 파일 수와 파일 인덱스(`buildfileindex`)가 필요합니다.
* 함의: `-B`도 같은 경로를 탑니다. 모든 기여 레코드를 unpack/pack 하지만, 인덱스 구조는 그대로입니다.
