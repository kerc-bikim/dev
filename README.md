# KERC seismic tools

Docker Compose 모노레포입니다. 앱 코드는 `apps/` 아래에 있고, 루트 `compose.yaml` 이 서비스를 묶습니다.

```
.
├── compose.yaml                 # 기본: Earthworm 웹. 프로필로 다른 앱
├── apps/
│   ├── earthworm_web/           # Earthworm 웹 콘솔 (FastAPI + React)
│   ├── stationxml_manager/
│   ├── PPSD_v1/
│   ├── ringserver_seedlink_websocket/
│   ├── dataselect/
│   ├── recvQSCD20/              # PyQt GUI — Compose 밖 (호스트/Xvfb)
│   └── seedlinkToMp3/
└── packages/                    # 공유 패키지 (비어 있음)
```

Earthworm 바이너리(Rocky tarball)는 이미지에 넣지 않습니다. 기본 스택은 웹 콘솔 + 시드 스텁입니다. 실제 `startstop` 은 `compose.override.example.yaml` 을 `compose.override.yaml` 로 복사해 `EW_HOME` 을 붙이고 `ipc: host` 를 켭니다.

## 실행

```bash
cp .env.example .env   # 선택
docker compose up --build
```

브라우저: http://127.0.0.1:8081  (Earthworm 웹)

다른 앱:

```bash
docker compose --profile ppsd up --build          # :8080
docker compose --profile stationxml up --build    # :8082
docker compose --profile ringserver up --build    # :8083
docker compose --profile tools run --rm dataselect -h
```

프로필은 겹쳐 쓸 수 있습니다.

```bash
docker compose --profile ppsd --profile stationxml up --build
```

## 포트

| 서비스 | 포트 |
|--------|------|
| Earthworm 웹 UI | 8081 |
| PPSD UI | 8080 |
| StationXML UI | 8082 |
| RingWave UI | 8083 |

API 컨테이너는 기본으로 호스트에 노출하지 않습니다. UI nginx 가 `/api` · `/ws` 를 프록시합니다.

## 앱별 로컬 개발 (Compose 없이)

```bash
cd apps/earthworm_web && cat README.md
```

Cursor Cloud 부트스트랩: `.cursor/install.sh` (경로가 `apps/` 기준).
