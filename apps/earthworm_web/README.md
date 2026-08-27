# Earthworm Web Control

Earthworm **v8.0b17** 를 웹에서 설정·기동·감시하는 콘솔입니다. 백엔드(FastAPI)와 프론트엔드(React + Vite)는 분리되어 있고, Earthworm 바이너리는 프론트가 직접 호출하지 않습니다.

계획서: [`plan.md`](plan.md) · 우선 모듈 [`plan_priority.md`](plan_priority.md) · 단계·MVP [`plan_mvp.md`](plan_mvp.md) · 작업자·이력 [`plan_ops.md`](plan_ops.md) · HTML [`plan.html`](plan.html) · 그림 [`diagrams/`](diagrams/) ([diagram-design](https://github.com/cathrynlavery/diagram-design))

## 개발 실행

기본값은 저장소 `fixtures/` 의 **CLI 스텁**을 `apps/earthworm_web/.ew_home` 에 심습니다. 실제 Rocky Linux 바이너리가 있으면 `EW_WEB_BASH` 와 `EW_WEB_AUTO_SEED=0` 으로 가리키면 됩니다.

Docker 모노레포 (저장소 루트):

```bash
docker compose up --build
# http://127.0.0.1:8081
```

```bash
# 백엔드 :8010
cd backend
pip install -r requirements.txt
EW_WEB_API_KEY=dev uvicorn app.main:app --host 0.0.0.0 --port 8010

# 프론트 :5174  (/api · /ws 프록시)
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5174
```

브라우저: http://127.0.0.1:5174

인증:

- 사람 UI 는 로그인 세션(HttpOnly 쿠키 `ew_session`)입니다. 프론트는 `credentials: include` 만 씁니다.
- WebSocket 은 `POST /api/auth/ws-ticket` 후 `?ticket=` 입니다. 비밀번호를 쿼리에 넣지 않습니다.
- `EW_WEB_API_KEY` 는 pytest · 서비스 합성 작업자(`service`, 역할 operator) 전용입니다. 사람 UI 에서 쓰지 마세요.
- `/api/health` 는 공개입니다.
- 작업자 테이블이 비어 있으면 `POST /api/auth/bootstrap` 또는 마법사 마지막 칸으로 최초 관리자를 만듭니다.
- 개발·CI 전용: `EW_WEB_BOOTSTRAP_USERNAME` / `EW_WEB_BOOTSTRAP_PASSWORD` (테이블이 비어 있을 때만 시드). 배포 시 비우세요.
- Swagger 는 기본 비활성. 켤 때만 `EW_WEB_OPEN_DOCS=1`.

```bash
cd backend && pytest
cd frontend && npm run build
```

## 동작 요약

1. **초기 설정 마법사** — `EW_HOME` / `EW_RUN_DIR`(params, log, data), Inst ID, 링 이름·키·크기·순서. 완료 전 제어 API 는 409.
2. **이후 설정** — 우선 모듈 팔레트·구성 보드, 작업자·이력, 모듈 토글·복제, 통합 변수, 파일 편집, 시작(`startstop`)/종료(`pau`)/일시중지(`stopmodule` pid)/재개(`restart` pid), 대시보드, 로그, sniffwave/sniffring. 복제 다발 후보는 `q3302ew` · `slink2ew` · `export_scnl` · `export_generic` · `wave_serverV`.
3. 첫 startstop 링은 `STATUS_RING`. `FLAG_RING` 은 startstop 목록에 넣지 않습니다.
4. 목 미리보기(백엔드 없음): `frontend/preview/` 에서 `python3 -m http.server 8765`
