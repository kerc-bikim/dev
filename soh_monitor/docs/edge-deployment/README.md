# 지역 Edge Collector 설치

Edge 는 관측소 사설망에 두고 기록계를 수집한다. 중앙으로는 **HTTPS 443 Outbound 만**
나간다. 들어오는 포트는 열지 않는다. PostgreSQL·InfluxDB·Grafana 는 Edge 에 두지 않는다.

등록이 끝나면 일회용 Token 은 버리고, 이후 통신은 발급받은 클라이언트 토큰(운영 mTLS 는
M8)으로만 한다. 중앙이 꺼져 있어도 수집은 멈추지 않고 로컬 Spool 에 쌓인다.

## 전제

- 지역 서버가 기록계 대역(기본 RFC1918)에 붙어 있다
- 중앙 `https://<중앙 호스트>` 로 443 Outbound 가 열려 있다
- Docker 와 Compose 플러그인이 있다
- 중앙 관리자(ADMIN) 계정이 있다

## 1. 중앙에서 Edge 만들기

관리 API (또는 이후 M8 화면)에서 Edge 를 만든다. Token 은 **응답에 한 번만** 실리고
저장소에는 해시만 남는다.

```bash
curl -sS -c cookies -X POST https://monitoring.example.org/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<비밀번호>"}'

curl -sS -b cookies -X POST https://monitoring.example.org/api/v1/edges \
  -H 'Content-Type: application/json' \
  -d '{"edgeCode":"edge-region-a-01","name":"중부 지역 Edge"}'
```

응답의 `enrollmentToken` 과 `edgeCode` 를 적는다. 이 값을 다시 조회할 수 없다.
분실하면 `POST /api/v1/edges/{id}/enrollment-token` 으로 재발급한다. 이전 Token 은
즉시 무효가 된다.

## 2. 지역 서버 준비

저장소 루트에서:

```bash
cp deploy/examples/edge.env.example edge.env
mkdir -p secrets
# secrets/device_credential_key 에 기록계 인증정보 복호화 키를 둔다
```

`edge.env` 에서 다음을 채운다.

| 변수 | 의미 |
|------|------|
| `SOH_EDGE_ID` | 중앙에 등록한 `edgeCode` |
| `SOH_CENTRAL_URL` | 중앙 주소. `https://monitoring.example.org` |
| `SOH_EDGE_ENROLLMENT_TOKEN` | 1단계에서 받은 일회용 Token |

기록계 IP 는 이 파일에 적지 않는다. 어느 장비를 수집할지는 중앙 설정이 내려준다.

## 3. 기동

```bash
docker compose -f deploy/compose/compose.edge.yml --env-file edge.env up -d
# 또는 저장소 루트에서
make edge-up
```

기동 직후 Edge 는 중앙 `POST /api/v1/edge/enroll` 을 호출한다. 성공하면

- Token 환경변수는 다음 기동 전에 `edge.env` 에서 지운다
- 인증서 자리 표시와 클라이언트 토큰이 Spool 볼륨 `/var/lib/soh-edge/certs` 에 남는다
- 이후 Tick 은 Heartbeat · 설정 동기 · 수집 · 업로드만 수행한다

들어오는 포트가 없는지 `docker compose ... ps` 로 확인한다.

## 4. 장비 할당

중앙에서 기록계를 `collectionMode=EDGE` 로 두고 이 Edge 에 할당한다.

```bash
curl -sS -b cookies -X POST https://monitoring.example.org/api/v1/edges/<edge-uuid>/assignments \
  -H 'Content-Type: application/json' \
  -d '{"deviceId":"<device-uuid>"}'
```

다음 설정 동기 Tick (`GET /api/v1/edge/config`) 에서 장비가 내려오고 수집이 시작된다.
잘못된 설정은 Edge 가 적용하지 않고 이전 버전을 유지한다.

## 5. 정상 동작 확인

```bash
curl -sS -b cookies https://monitoring.example.org/api/v1/edges/<edge-uuid>/health
```

- `lastHeartbeatAt` 이 수십 초 안에 갱신된다
- `lastConfigAppliedVersion` 이 할당 이후 버전과 같다
- Spool 사용량이 한도(기본 5GB, 80% 주의 / 90% 장애) 안에 있다

중앙을 잠시 꺼도 지역 서버의 `/var/lib/soh-edge/segments` 파일 수가 늘어나야 한다.
중앙을 다시 켜면 오래된 `sequence` 부터 올라가고, 같은 `batchId` 를 다시 보내도
한 번만 반영된다.

## 6. 연결 시험

EDGE 장비의 `POST /api/v1/devices/{id}/test-connection` 은 중앙이 기록계로 나가지
않는다. Edge 가 Heartbeat 로 작업을 받아 대행하고 결과를 올린다.

## 운영 주의

- Spool 볼륨을 지우면 ACK 받지 못한 수집분이 사라진다. 컨테이너만 갈아도 볼륨은 남긴다
- Adapter 자동 업데이트는 하지 않는다. 새 Adapter 는 이미지를 다시 빌드해 배포한다
- 운영 mTLS(클라이언트 인증서 검증·폐기)는 M8 에서 연다. 지금은 HMAC 클라이언트 토큰이다
- Edge 간 통신은 없다. 같은 장비를 두 Edge 에 동시에 할당하면 DB 가 거부한다
