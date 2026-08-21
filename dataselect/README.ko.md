# dataselect — miniSEED 선택·정렬·블록 크기 지정

[EarthScope/dataselect](https://github.com/EarthScope/dataselect) 를 기반으로, 출력 miniSEED **블록(레코드) 크기**를 `-B` 로 지정할 수 있게 확장한 버전입니다.

원본 동작(선택, 시간 정렬, overlap 제거 등)은 그대로 두고, 저장할 때만 레코드를 풀어 다시 패킹합니다. `-B` 를 주지 않으면 기존과 같이 입력 레코드 길이를 유지합니다.

## 빌드

C99 컴파일러와 GNU make 가 필요합니다.

```
make
```

생성된 `dataselect` 바이너리를 PATH 에 복사해 사용합니다.

## `-B` 옵션

```
dataselect -B 512 -o output.mseed input.mseed
```

| 항목 | 내용 |
|------|------|
| 형식 | `-B bytes` |
| 허용 값 | 128 ~ 131072 사이의 **2의 거듭제곱** (예: 256, 512, 1024, 4096, 8192) |
| 동작 | 같은 채널이 시간상 이어지면 샘플을 모아 블록을 채운 뒤에만 기록. 갭·채널 변경·출력 끝에서만 짧은 레코드를 씀 |
| 데이터 | **샘플 시각과 값은 원본과 동일**. 바뀌는 것은 레코드(블록) 프레이밍뿐 |
| 예 | 입력이 4096 byte 레코드이면 `-B 512` 로 512 byte 레코드 여러 개로 저장 |

입력 레코드가 지정 크기보다 크면 샘플을 여러 레코드로 나눕니다. 지정 크기가 더 크고 같은 채널이 시간상 이어지면 샘플을 모아 큰 레코드를 채웁니다.

miniSEED 2는 요청한 길이로 고정(패딩 포함)되고, **출력 파일마다** 채널(SourceID) 기준으로 시퀀스 번호를 **000001**부터 다시 매깁니다. SDS 날짜 파일이 바뀌면 번호가 이어지지 않고 다시 1부터 시작합니다. miniSEED 3 고정 헤더에는 시퀀스가 없습니다. `-B` 없이 복사하면 원본 바이트(시퀀스 포함)를 유지합니다.

miniSEED 2는 요청한 길이로 고정(패딩 포함)되고, miniSEED 3은 그 길이를 최대값으로 씁니다.

unpack/pack 할 수 없는 인코딩이거나 헤더가 블록보다 크면, 원본을 그대로 섞어 쓰지 않고 오류로 종료합니다. Steim으로 다시 압축할 때 이어 붙인 샘플 차이가 인코딩 한도를 넘으면 같은 오류가 납니다.

## 다른 출력 옵션과 함께 쓰기

```
# 단일 파일
dataselect -B 512 -o out.mseed data.mseed

# SDS 아카이브 레이아웃
dataselect -B 512 -SDS /archive data.mseed

# 시간창 자르기 + 블록 크기 변경
dataselect -B 512 -Ps -ts 2024-01-01T00:00:00 -te 2024-01-01T01:00:00 -o out.mseed data.mseed
```

전체 옵션은 `dataselect -h` 또는 [doc/dataselect.md](doc/dataselect.md) 를 참고하세요.

## 원본이 버전업된 경우

`-B` 구현은 `src/local.c` / `src/local.h` 에 있고, 원본 `src/dataselect.c` 에는 `LOCAL` 표시 훅만 있습니다. EarthScope dataselect 를 새로 가져올 때는 그 훅을 다시 붙이면 됩니다. 절차는 [UPSTREAM.md](UPSTREAM.md) 를 참고하세요.
