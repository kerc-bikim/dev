# PDCC Web — 에이전트 안내

이 디렉터리(`pdcc_web/`)만 고칩니다. 레포 루트의 PPSD, Earthworm, ringserver, `stationxml_manager`와 의존성·커밋을 섞지 않습니다.

자세한 기능·환경 변수는 [`README.md`](README.md)입니다. 고정 프롬프트는 [`docs/prompts/`](docs/prompts/README.md)입니다.

## 제품 불변식

1. 브라우저는 NRL(EarthScope)에 직접 호출하지 않습니다. `apps/web`에는 NRL 베이스 URL이 없습니다.
2. Inventory 진실은 StationXML **원문**입니다. 저장 경로에서 ObsPy `Inventory.write()`로 전체 문서를 재생성하지 않습니다.
3. NRL은 API **기동 시** 호출하지 않습니다.
4. UI·API 오류 문구는 한국어입니다.
5. 조회자는 편집·NRL 적용·SEED/RESP·위저드·초안이 403입니다.
6. 업로드는 `.xml` / `.seed` / `.dataless` / `.resp`(또는 `RESP.*`)만입니다. zip·MiniSEED·full SEED는 거절합니다.
7. 새 동작은 ADR을 남기거나 기존 ADR을 고칩니다. `docs/adr/`가 계약입니다.

슬라이스를 구현할 때는 [`docs/prompts/product.md`](docs/prompts/product.md)와 [`docs/prompts/implement-slice.md`](docs/prompts/implement-slice.md)를 따릅니다. 이미 끝난 범위는 [`docs/prompts/completed-m0-m4.md`](docs/prompts/completed-m0-m4.md)를 보고 다시 만들지 않습니다.

## 로컬·Cloud 실행

| 서비스 | 주소 |
|--------|------|
| API | `http://127.0.0.1:8080` 헬스 `/health` 또는 `/api/health` |
| 웹 | `http://127.0.0.1:3000` |
| Postgres | `127.0.0.1:5432` DB `pdcc` / 사용자 `pdcc` |
| Redis | `127.0.0.1:6379` |

호스트 API 환경 변수:

```bash
export DATABASE_URL=postgresql+psycopg://pdcc:pdcc@127.0.0.1:5432/pdcc
export REDIS_URL=redis://127.0.0.1:6379/0
export DEV_BOOTSTRAP_ADMIN=true
```

로그인: `stub`/`stub`, `stub2`/`stub2`, 플래그가 켜진 경우 `admin`/`admin`.

Cloud에서 API·Vite가 이미 떠 있으면 tmux 세션 `pdcc-api-8080`, `pdcc-vite-3000`을 재사용합니다. 코드를 반영하려면 **해당 PID만** 종료한 뒤 같은 세션에서 uvicorn을 다시 띄웁니다. `pkill -f`는 쓰지 않습니다.

Redis가 없으면 세션·잠금·NRL 캐시·알림이 실패합니다. 배포 Redis가 없을 때는 fakeredis `TcpFakeServer(("127.0.0.1", 6379))`로 대행할 수 있습니다. `java`는 있을 수 있으나 `infra/jars/`에 validator JAR가 없으면 Python 대체 경로가 정상입니다.

## 테스트

```bash
cd pdcc_web/apps/api
. .venv/bin/activate
python -m pytest --ignore=tests/test_ops.py -q
```

- `tests/test_ops.py`는 이 스택의 기본 경로가 아닙니다. 커밋하지 않은 잔여와 섞지 마십시오.
- API venv(`apps/api/.venv`)만 씁니다. 루트 `.venv`와 섞지 않습니다.
- 웹 UI·레이아웃·라우팅·클라이언트 상태를 바꿨으면 브라우저에서 해당 흐름을 끝까지 클릭합니다. computer use가 없으면 라이브 API(`curl` + 쿠키)와 Vite 소스 조회로 대체하고, GUI를 확인하지 못했다고 명시합니다.
- 라이브 검증 전에 코드가 올라간 API 프로세스인지 확인합니다. `--reload`가 없으면 재시작이 필요합니다.

## 커밋

- `pdcc_web/` 안의 해당 슬라이스만 스테이징합니다.
- `ringserver_seedlink_websocket/frontend/package-lock.json` 등 무관한 dirty 파일은 커밋하지 않습니다.
- 임시 디버그 로그는 커밋 전에 제거합니다.
- 브랜치 이름은 `cursor/<descriptive-name>-5867` (소문자)입니다.
