"""Edge 설정·Ingest Schema 검증.

Edge 는 지역망에 떨어져 있어 잘못된 Payload 를 사후에 고치기 어렵다.
Schema 로 형태를 못 박아 둔다.
"""
from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from app.metrics.catalog import CONTRACTS_DIR

CONFIG_SCHEMA = json.loads((CONTRACTS_DIR / "edge" / "config.schema.json").read_text("utf-8"))
INGEST_SCHEMA = json.loads((CONTRACTS_DIR / "edge" / "ingest.schema.json").read_text("utf-8"))

VALID_CONFIG = {
    "configVersion": 42,
    "edgeId": "edge-region-a-01",
    "issuedAt": "2026-08-27T00:00:00Z",
    "devices": [
        {
            "deviceId": "d-001",
            "stationCode": "A01",
            "adapterKey": "nanometrics.centaur.ctr",
            "adapterVersion": "1.0",
            "assignmentEpoch": 3,
            "enabled": True,
            "pollIntervalMinutes": 5,
            "connection": {"hostname": "10.10.1.20", "scheme": "http"},
            "credential": {"reference": "secret://devices/d-001"},
        }
    ],
}

VALID_BATCH = {
    "edgeId": "edge-region-a-01",
    "batchId": "8f14e45f-ea6d-4b1e-9f2a-1234567890ab",
    "configVersion": 42,
    "firstSequence": 10001,
    "lastSequence": 10001,
    "polls": [
        {
            "pollId": "01J8Z5T9Q0ABCDEF",
            "sequence": 10001,
            "deviceId": "d-001",
            "observedAt": "2026-08-27T00:05:00Z",
            "success": True,
            "latencyMs": 132.4,
            "samples": [
                {"metricKey": "connectivity.reachable", "valueBool": True},
                {"metricKey": "power.input_voltage_v", "valueFloat": 12.6},
                {
                    "metricKey": "sensor.mass_position_v",
                    "dimensions": {"sensor_port": "A", "axis": "U"},
                    "valueFloat": 0.31,
                },
                {
                    "metricKey": "storage.sd_status",
                    "valueStatus": "WARNING",
                    "rawValue": "not present",
                },
                {
                    "metricKey": "storage.sd_free_bytes",
                    "supportState": "UNSUPPORTED",
                },
            ],
        }
    ],
}


def _validate(schema: dict, document: dict) -> list[str]:
    validator = Draft202012Validator(schema)
    return [error.message for error in validator.iter_errors(document)]


def test_Schema_자체가_유효하다():
    Draft202012Validator.check_schema(CONFIG_SCHEMA)
    Draft202012Validator.check_schema(INGEST_SCHEMA)


def test_정상_설정은_통과한다():
    assert _validate(CONFIG_SCHEMA, copy.deepcopy(VALID_CONFIG)) == []


def test_할당_세대가_없으면_거부한다():
    """assignmentEpoch 이 없으면 이중 수집을 막을 수 없다."""
    document = copy.deepcopy(VALID_CONFIG)
    del document["devices"][0]["assignmentEpoch"]
    assert _validate(CONFIG_SCHEMA, document) != []


def test_수집주기_범위를_벗어나면_거부한다():
    document = copy.deepcopy(VALID_CONFIG)
    document["devices"][0]["pollIntervalMinutes"] = 0
    assert _validate(CONFIG_SCHEMA, document) != []

    document["devices"][0]["pollIntervalMinutes"] = 5000
    assert _validate(CONFIG_SCHEMA, document) != []


def test_설정에_모르는_최상위_항목이_있으면_거부한다():
    document = copy.deepcopy(VALID_CONFIG)
    document["unexpectedField"] = 1
    assert _validate(CONFIG_SCHEMA, document) != []


def test_정상_Batch는_통과한다():
    assert _validate(INGEST_SCHEMA, copy.deepcopy(VALID_BATCH)) == []


def test_Batch에는_멱등키가_필요하다():
    document = copy.deepcopy(VALID_BATCH)
    del document["batchId"]
    assert _validate(INGEST_SCHEMA, document) != []


def test_관측시각이_없는_Poll은_거부한다():
    """observedAt 이 없으면 늦게 도착한 데이터를 원래 시각에 채울 수 없다."""
    document = copy.deepcopy(VALID_BATCH)
    del document["polls"][0]["observedAt"]
    assert _validate(INGEST_SCHEMA, document) != []


def test_표준_상태값만_받는다():
    document = copy.deepcopy(VALID_BATCH)
    document["polls"][0]["samples"][3]["valueStatus"] = "SORT_OF_OK"
    assert _validate(INGEST_SCHEMA, document) != []


def test_실패한_Poll도_전송할_수_있다():
    document = copy.deepcopy(VALID_BATCH)
    document["polls"][0].update(
        {"success": False, "errorCode": "REQUEST_TIMEOUT", "samples": []}
    )
    assert _validate(INGEST_SCHEMA, document) == []


def test_Batch에_Poll이_하나도_없으면_거부한다():
    document = copy.deepcopy(VALID_BATCH)
    document["polls"] = []
    assert _validate(INGEST_SCHEMA, document) != []


def test_Batch의_모든_metricKey는_카탈로그에_있다():
    from app.metrics.catalog import load_catalog

    catalog = load_catalog()
    for sample in VALID_BATCH["polls"][0]["samples"]:
        assert sample["metricKey"] in catalog.metrics
