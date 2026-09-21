SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
COMPOSE_DEV := deploy/compose/compose.dev.yml
COMPOSE_CENTRAL := deploy/compose/compose.central.yml
COMPOSE_EDGE := deploy/compose/compose.edge.yml

# 로컬(컨테이너 없이) 실행할 때는 SQLite 로 스키마만 확인한다. 운영 DB 는 PostgreSQL 이다.
LOCAL_DB ?= sqlite:////tmp/soh_local.db

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------ 로컬 개발

.PHONY: venv
venv: ## 백엔드 가상환경 생성과 의존성 설치
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt

.PHONY: install
install: venv ## 백엔드·프론트엔드 의존성 설치
	cd frontend && npm install

.PHONY: api
api: ## 로컬 API 실행 (SQLite)
	cd backend && SOH_DATABASE_URL_OVERRIDE=$(LOCAL_DB) ../$(PY) -m app.main_api

.PHONY: collector
collector: ## 로컬 Collector 실행 (SQLite)
	cd backend && SOH_DATABASE_URL_OVERRIDE=$(LOCAL_DB) ../$(PY) -m app.main_collector

.PHONY: edge
edge: ## 로컬 Edge Agent 실행 (SQLite Spool)
	cd backend && SOH_EDGE_SPOOL_PATH=/tmp/soh-edge-spool ../$(PY) -m app.main_edge

.PHONY: web
web: ## 로컬 프론트엔드 개발 서버
	cd frontend && npm run dev

.PHONY: migrate
migrate: ## 마이그레이션 적용과 초기 데이터 적재
	cd backend && SOH_DATABASE_URL_OVERRIDE=$(LOCAL_DB) ../$(PY) -m app.main_migrate

.PHONY: revision
revision: ## 모델 변경으로부터 마이그레이션 생성 (m="설명")
	cd backend && SOH_DATABASE_URL_OVERRIDE=$(LOCAL_DB) ../$(VENV)/bin/alembic revision --autogenerate -m "$(m)"

# ------------------------------------------------------------------ 계약

.PHONY: contracts
contracts: ## 카탈로그에서 백엔드 상수·프론트 타입 생성, OpenAPI 추출
	$(PY) scripts/gen_metrics.py
	$(PY) scripts/export_openapi.py

.PHONY: fixtures
fixtures: ## 가상 서버 응답을 Fixture 로 다시 떠 놓기
	$(PY) scripts/capture_fixtures.py

.PHONY: mock
mock: ## 가상 Centaur CTR 서버 실행 (http://127.0.0.1:8090)
	PYTHONPATH=. $(PY) -m mock.centaur_mock

.PHONY: mock-seedlink
mock-seedlink: ## 가상 SeedLink 서버 실행 (seedlink://127.0.0.1:18000)
	PYTHONPATH=backend:. $(PY) -m mock.seedlink_mock.server

.PHONY: mock-load
mock-load: ## 부하 시험용 가상 기록계 100대 (20% 느린 장비)
	PYTHONPATH=. MOCK_FLEET_SIZE=100 MOCK_SLOW_RATIO=0.2 MOCK_PORT=8091 $(PY) -m mock.centaur_mock

.PHONY: soak
soak: ## 수집기 부하·안정성 시험 (기본 50대 5회)
	$(PY) scripts/soak_collector.py --devices $(or $(devices),50) --ticks $(or $(ticks),5)

.PHONY: backup
backup: ## 설정 DB·Grafana·Influx Task 백업 묶음 (OUT=/var/backups/soh)
	$(PY) scripts/ops_backup.py --out $(or $(OUT),/tmp/soh-backup) --database $(LOCAL_DB)

.PHONY: restore
restore: ## 백업 묶음 복구 (ARCHIVE=... DATABASE=$(LOCAL_DB))
	$(PY) scripts/ops_restore.py --archive "$(ARCHIVE)" --database $(or $(DATABASE),$(LOCAL_DB))

.PHONY: secrets-check
secrets-check: ## Git 에 비밀이 남았는지 검사
	$(PY) scripts/check_secrets.py

.PHONY: contracts-check
contracts-check: ## 생성물이 카탈로그·OpenAPI 와 일치하는지 검사 (CI 게이트)
	$(PY) scripts/gen_metrics.py --check
	$(PY) scripts/export_openapi.py --check
	$(PY) scripts/gen_grafana.py --check

.PHONY: grafana
grafana: ## Grafana 대시보드 JSON 생성
	$(PY) scripts/gen_grafana.py

.PHONY: naming-check
naming-check: ## 공통 계층에 제조사 이름이 새어 들어왔는지 검사 (CI 게이트)
	$(PY) scripts/check_naming.py

# ------------------------------------------------------------------ 검증

.PHONY: test
test: ## 백엔드 테스트
	cd backend && ../$(PY) -m pytest

.PHONY: typecheck
typecheck: ## 프론트엔드 타입 검사
	cd frontend && npm run typecheck

.PHONY: build-web
build-web: ## 프론트엔드 빌드
	cd frontend && npm run build

.PHONY: verify
verify: contracts-check naming-check secrets-check test typecheck build-web ## 커밋 전 전체 검증
	@echo "전체 검증 통과"

# ------------------------------------------------------------------ Docker

.PHONY: dev
dev: ## 개발 스택 기동 (Docker)
	docker compose -f $(COMPOSE_DEV) up -d --build

.PHONY: dev-mock
dev-mock: ## 개발 스택 + 가상 기록계 기동
	docker compose -f $(COMPOSE_DEV) --profile mock up -d --build

.PHONY: dev-load
dev-load: ## 개발 스택 + 부하 시험용 가상 기록계 100대
	docker compose -f $(COMPOSE_DEV) --profile load up -d --build

.PHONY: dev-logs
dev-logs: ## 개발 스택 로그
	docker compose -f $(COMPOSE_DEV) logs -f --tail=100

.PHONY: down
down: ## 개발 스택 종료
	docker compose -f $(COMPOSE_DEV) down

.PHONY: central-up
central-up: ## 중앙 스택 기동 (central.env 필요)
	docker compose -f $(COMPOSE_CENTRAL) --env-file central.env up -d

.PHONY: edge-up
edge-up: ## 지역 Edge 기동 (edge.env 필요)
	docker compose -f $(COMPOSE_EDGE) --env-file edge.env up -d

.PHONY: images
images: ## 배포 이미지 빌드
	docker build -f deploy/docker/Dockerfile.backend --target runtime-api       -t soh-api:latest .
	docker build -f deploy/docker/Dockerfile.backend --target runtime-collector -t soh-collector:latest .
	docker build -f deploy/docker/Dockerfile.backend --target runtime-migrate   -t soh-migrate:latest .
	docker build -f deploy/docker/Dockerfile.edge                               -t soh-edge:latest .
	docker build -f deploy/docker/Dockerfile.web                                -t soh-web:latest .

# ------------------------------------------------------------------ 문서

.PHONY: docs-tools
docs-tools: ## 문서 변환 도구 설치
	$(PIP) install -r scripts/requirements.txt

.PHONY: plan-html
plan-html: ## plan.md 를 plan.html 로 변환
	$(PY) scripts/build_plan_html.py
