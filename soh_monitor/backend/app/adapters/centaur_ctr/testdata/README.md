# Centaur CTR 응답 Fixture

Adapter 회귀 시험의 기준이 되는 파일들이다. 파일명 접두가 성격을 가른다.

| 접두 | 의미 |
|------|------|
| `real-` | **실장비에서 받은 응답.** 응답 형식의 권위는 이 파일들이다 |
| `synthetic-` | 가상 서버가 만든 응답. 실장비 Fixture 가 없는 동안의 대체물 |

## 왜 구분하는가

가상 서버를 정교하게 만들면 Adapter 가 **우리 상상**에 맞춰 완성되고, 실장비를 붙이는
순간 처음부터 다시 하게 된다. 그래서 `real-` 파일이 하나라도 들어오면
`test_fixture_divergence` 가 켜지고, 가상 서버 기준선과 실응답의 채널 집합이 어긋나면
시험이 실패한다. 가상 서버가 조용히 현실에서 멀어지는 것을 막는 장치다.

## 실장비 응답을 넣는 방법 (조사 항목 M-1.2)

```bash
curl -s "http://<기록계IP>/api/v1/instruments/soh?pretty=true" \
  -o real-ctr6-normal.json
```

익명화 규칙

- 시리얼·Instrument ID 는 `centaur-6__0000` 형태로 바꾼다
- 위도·경도는 소수점 2자리까지만 남긴다
- 그 외 값은 **바꾸지 않는다.** 값을 다듬으면 시험의 의미가 사라진다

확보 목표는 `docs/inventory.md` 의 M-1.2 표에 있다.

## synthetic 파일 재생성

```bash
python scripts/capture_fixtures.py
```

시각을 고정해 만들기 때문에 실행마다 내용이 바뀌지 않는다.
