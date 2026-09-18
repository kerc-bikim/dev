# 설치

담당자가 바뀌어도 이 문서와 예시 env 만으로 중앙·Edge 를 올린다.

## 준비

- Docker 와 Compose
- `deploy/examples/central.env.example` → `central.env`
- `secrets/` 6개 파일 (비밀번호·토큰·키). 값은 한 줄
- `certs/server.crt`, `certs/server.key`, (운영) `certs/edge-ca.crt`

로컬에서 Docker 없이 확인하려면 [`README.md`](../../README.md) 의 `make migrate && make api && make web`.

## 중앙

```bash
cd soh_monitor
cp deploy/examples/central.env.example central.env
mkdir -p secrets certs
# secrets/* 와 certs/* 를 채운다
make images
make central-up
```

확인:

- `https://<host>/` 관리 Web
- `https://<host>/grafana/` 대시보드 7종, 폴더 `관측소 SOH`
- `https://<host>/api/v1/auth/me` 는 로그인 전 401

PostgreSQL·InfluxDB 포트는 외부에 열리지 않아야 한다.

## Edge

[`../edge-deployment/README.md`](../edge-deployment/README.md) 를 따른다. 들어오는 포트는 열지 않는다.

```bash
cp deploy/examples/edge.env.example edge.env
make edge-up
```

일회용 Enrollment Token 은 화면에서 한 번만 보인다. 등록이 끝나면 파일에서 지운다.

## 첫 관리자

`make migrate` 가 비밀번호를 한 번 출력한다. 첫 로그인에서 바꾼다.
`SOH_BOOTSTRAP_ADMIN_PASSWORD` 를 쓰면 그 값으로 만들고 역시 변경을 강제한다.
