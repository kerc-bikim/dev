# 원본(EarthScope dataselect) 버전업 시 `-B` 재적용

이 트리는 [EarthScope/dataselect](https://github.com/EarthScope/dataselect) 에 **출력 레코드/블록 크기 `-B`** 를 더한 로컬 확장입니다.

- **로컬 로직**: `src/local.c`, `src/local.h` (상태, 파싱, pack 실패 처리, v2 시퀀스, 카운트)
- **원본에 가까운 파일**: `src/dataselect.c`, `src/dsarchive.c` — `/* >>> LOCAL */` … `/* <<< LOCAL */` 훅만 추가
- **버전 문자열**: `dataselect.c` 의 upstream `VERSION` 을 `local.h` 가 `4.4.0` 으로 덮어씀

원본이 버전업되면 **원본 `dataselect.c`를 가져온 뒤 훅을 다시 붙이면** `-B` 가 동작합니다. `local.c` / `local.h` 는 그대로 두면 됩니다.

## 1. 원본 소스 가져오기

```
git fetch https://github.com/EarthScope/dataselect.git master
# 또는 릴리스 타볼을 src/dataselect.c, src/dsarchive.c, src/dsarchive.h, libmseed/ 에 덮어쓰기
```

`src/Makefile` 의 `SRCS` 에 `local.c` 가 들어 있는지는 확인합니다.

```
SRCS = dataselect.c dsarchive.c local.c
```

## 2. `dataselect.c` 에서 `LOCAL` 검색 후 훅 재적용

이전 트리와 diff 하거나, 아래 위치에 같은 훅을 넣습니다.

| 위치 | 할 일 |
|------|--------|
| `#define VERSION` 다음 | `#include "local.h"` |
| `writetraces()` 시작 | `local_set_counters (&totalrecsout, &totalbytesout)` |
| trim 여부 `if` | `local_should_unpack (newrange && …)` 로 조건 확장, 호출 전 `local_pack_begin` |
| `rv == -2` | `-B` 이면 trimrecord 가 `-3` 을 돌려 원본 fallback 금지 |
| 레코드 카운트 루프 | `if (!local_write_counted ()) { totalrecsout++; … }` |
| `trimrecord()` | `do_trim` ( `-B` 만 있을 때 `newrange == NULL` 가능 ), 인코딩 거부, `local_prepare_pack`, pack 실패 시 `local_discard_original` |
| `writerecord()` | `-o` 경로에서 `local_stamp_v2_sequence` (파일 키 = outputfile), packed 레코드 `msr3_parse` 후 archive/`-out` 에 사용, `local_note_write` |
| `dsarchive.c` `ds_streamproc()` | write 직전 `local_stamp_v2_sequence` (파일 키 = archive filename) |
| `processparam()` | `-A` 다음 `-B` → `local_set_blocksize` |
| `usage()` | `LOCAL_USAGE_B` 매크로 ( `-A` 와 `-Pr` 사이 ) |

훅 본문은 이 저장소의 `dataselect.c` 에서 `LOCAL` 로 검색하면 됩니다.

## 3. 동작이 바뀌면 안 되는 것

- `-B` 없음 + trim 만: unpack/pack 불가면 **원본 레코드를 그대로 쓰고 경고** (기존과 동일)
- `-B` 지정: pack 불가·부분 실패·헤더가 블록보다 크면 **원본을 섞지 않고 종료 코드 1**
- v2 시퀀스는 **각 출력 파일**에서 채널마다 1부터 증가. 아카이브 파일이 바뀌면 이어지지 않음
- 샘플 시각·값은 원본과 동일 (`make test` 의 `compare-series`)

## 4. 확인

```
make test
```

`BlockSize` 테스트 그룹이 `-B` 경로를 검사합니다.
