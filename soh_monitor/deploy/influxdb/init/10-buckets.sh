#!/bin/bash
# InfluxDB 초기화. 컨테이너 첫 기동 때 한 번 실행된다.
#
# 보존정책은 계획서 6절을 따른다.
#   원본       180일
#   5분 집계   2년
#   1시간 집계 5년
# 장애 이력은 PostgreSQL 에 영구 보관하므로 여기서 다루지 않는다.
set -euo pipefail

ORG="${DOCKER_INFLUXDB_INIT_ORG:-observatory}"
RAW_BUCKET="${DOCKER_INFLUXDB_INIT_BUCKET:-soh}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[soh] 원본 Bucket 보존 180일"
influx bucket update --name "$RAW_BUCKET" --retention 180d || true

echo "[soh] 집계 Bucket 생성"
influx bucket create --org "$ORG" --name "${RAW_BUCKET}_5m" --retention 730d || true
influx bucket create --org "$ORG" --name "${RAW_BUCKET}_1h" --retention 1825d || true

echo "[soh] 다운샘플링 Task 등록"
# Task 본문은 Git 이 원본이다. 이 스크립트는 등록만 한다.
influx task create --org "$ORG" --file "${HERE}/downsample_5m.flux" || true
influx task create --org "$ORG" --file "${HERE}/downsample_1h.flux" || true

echo "[soh] 초기화 완료"
