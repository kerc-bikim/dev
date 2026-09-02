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

echo "[soh] 집계 Bucket 생성"
influx bucket create --org "$ORG" --name "${RAW_BUCKET}_5m" --retention 730d || true
influx bucket create --org "$ORG" --name "${RAW_BUCKET}_1h" --retention 1825d || true

echo "[soh] 다운샘플링 Task 등록"
cat <<FLUX > /tmp/downsample_5m.flux
option task = {name: "soh downsample 5m", every: 5m, offset: 1m}

from(bucket: "${RAW_BUCKET}")
  |> range(start: -task.every)
  |> filter(fn: (r) => r._measurement =~ /^recorder_/ or r._measurement == "edge_health")
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
  |> to(bucket: "${RAW_BUCKET}_5m", org: "${ORG}")
FLUX

cat <<FLUX > /tmp/downsample_1h.flux
option task = {name: "soh downsample 1h", every: 1h, offset: 5m}

from(bucket: "${RAW_BUCKET}_5m")
  |> range(start: -task.every)
  |> filter(fn: (r) => r._measurement =~ /^recorder_/ or r._measurement == "edge_health")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> to(bucket: "${RAW_BUCKET}_1h", org: "${ORG}")
FLUX

influx task create --org "$ORG" --file /tmp/downsample_5m.flux || true
influx task create --org "$ORG" --file /tmp/downsample_1h.flux || true

echo "[soh] 초기화 완료"
