# 0002. `-B`는 local.c, 원본에는 훅만

* 상태: Accepted
* 날짜: 2026-08
* 관련: `src/local.c`, `src/local.h`, `UPSTREAM.md`

## 맥락

EarthScope dataselect는 계속 버전업됩니다. 블록 크기·시퀀스·pack 실패 정책을 `dataselect.c`에 직접 넣으면 매 머지마다 충돌이 납니다.

## 결정

로컬 상태와 규칙은 `local.c` / `local.h`에 둡니다. `dataselect.c`에는 `/* >>> LOCAL */` 훅만 남기고, `VERSION`은 `local.h`가 4.4.0으로 덮어씁니다. 훅 위치와 “바꾸면 안 되는 동작”은 `UPSTREAM.md`에 적습니다.

`dsarchive.c`는 이 브랜치에서 훅이 없습니다. 아카이브는 `writerecord()`가 넘기는 `reclen`과 (필요 시) 파싱된 `MS3Record`를 씁니다.

## 결과

* 장점: 원본 `dataselect.c`를 가져온 뒤 LOCAL 검색으로 `-B`를 다시 붙일 수 있습니다.
* 단점: 훅이 빠지면 `-B`가 조용히 동작하지 않습니다. 머지 후 `make test`의 `BlockSize`가 필수입니다.
* 함의: `-B` 동작 변경은 가능하면 `local.c`에만 넣습니다. `dataselect.c` 훅을 늘리면 `UPSTREAM.md` 표를 같이 고칩니다.
