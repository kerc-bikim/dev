"""CLI 동작과 종료코드 검증."""

from __future__ import annotations

import argparse
import csv
import json

import pytest

from latlon_converter.cli import build_parser, main
from latlon_converter.errors import EXIT_AUTH, EXIT_INPUT, EXIT_OK
from latlon_converter.providers.mock import MOCK_LABEL


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    """테스트는 항상 mock 제공자로, 캐시 없이 돈다."""
    monkeypatch.setenv("LATLON_PROVIDER", "mock")
    monkeypatch.setenv("LATLON_CACHE_DB", "")
    monkeypatch.delenv("VWORLD_API_KEY", raising=False)


def test_point_table_output(capsys):
    assert main(["point", "--lat", "37.50435", "--lon", "127.02505"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "서울특별시 강남구 역삼동 808" in out
    assert "1168010100108080000" in out
    assert "소유구분" in out and "개인" in out
    assert "거주지구분" in out and "시도내" in out
    assert "등기사항증명서" in out


def test_point_json_output(capsys):
    assert main(["point", "--lat", "37.50435", "--lon", "127.02505", "--with-road", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["found"] is True
    assert payload["parcel"]["road_address"] == "서울특별시 강남구 테헤란로 305"
    assert payload["ledger"]["ownership_type"] == "개인"
    assert payload["ledger"]["residence_type"] == "시도내"
    assert payload["ledger"]["ownership_agency"] == ""
    assert "등기사항증명서" in payload["owner_name_notice"]


def test_point_csv_output(capsys):
    assert main(["point", "--lat", "37.50435", "--lon", "127.02505", "--csv"]) == EXIT_OK
    rows = list(csv.DictReader(capsys.readouterr().out.splitlines()))
    assert len(rows) == 1
    assert rows[0]["PNU"] == "1168010100108080000"
    assert rows[0]["지목"] == "대"
    assert rows[0]["거주지구분"] == "시도내"
    assert rows[0]["국가기관구분"] == ""


def test_verbose_writes_lookup_logs_to_stderr(capsys):
    assert main(["point", "--lat", "37.50435", "--lon", "127.02505", "-v"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "서울특별시 강남구 역삼동 808" in captured.out
    assert "좌표 조회" in captured.err
    assert "필지" in captured.err
    assert "소유구분=개인" in captured.err


def test_point_without_parcel_is_still_success(capsys):
    assert main(["point", "--lat", "36.0", "--lon", "130.5"]) == EXIT_OK
    assert "필지를 찾지 못했습니다" in capsys.readouterr().out


def test_point_rejects_out_of_range_coordinate(capsys):
    assert main(["point", "--lat", "95", "--lon", "127"]) == EXIT_INPUT
    assert "위도는 -90~90" in capsys.readouterr().err


def test_pnu_lookup(capsys):
    assert main(["pnu", "--pnu", "4215038023200120003"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "산 12-3" in out
    assert "국유지" in out
    assert "중앙부처" in out


def test_pnu_rejects_bad_value(capsys):
    assert main(["pnu", "--pnu", "12345"]) == EXIT_INPUT
    assert "19자리" in capsys.readouterr().err


def test_search_fixture_address(capsys):
    assert main(["search", "--query", "서울특별시 강남구 역삼동 808"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "역삼동 808" in out
    assert "37.504350" in out


def test_point_tokyo_crs_notes_transform(capsys):
    assert main(["point", "--lat", "37.50435", "--lon", "127.02505", "--crs", "tokyo"]) == EXIT_OK
    assert "동경측지계" in capsys.readouterr().out


def test_vworld_without_key_exits_with_auth_code(capsys, monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "")
    assert main(["point", "--lat", "37.5", "--lon", "127.0", "--provider", "vworld"]) == EXIT_AUTH
    assert "VWORLD_API_KEY" in capsys.readouterr().err


def write_csv(path, rows, header="관측소코드,위도,경도"):
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_batch_writes_output_and_keeps_input_columns(tmp_path, capsys):
    source = write_csv(
        tmp_path / "in.csv",
        ["KRC01,37.50435,127.02505", "KRC05,36.0,130.5"],
    )
    output = tmp_path / "out" / "result.csv"
    assert main(["batch", "--input", str(source), "--output", str(output), "--sleep", "0"]) == EXIT_OK

    rows = list(csv.DictReader(output.read_text(encoding="utf-8-sig").splitlines()))
    assert [row["관측소코드"] for row in rows] == ["KRC01", "KRC05"]
    assert rows[0]["지번주소"] == "서울특별시 강남구 역삼동 808"
    assert rows[1]["PNU"] == ""
    assert "필지를 찾지 못했습니다" in rows[1]["비고"]
    assert "2행을" in capsys.readouterr().err


def test_batch_detects_english_columns(tmp_path):
    source = write_csv(
        tmp_path / "in.csv",
        ["KRC01,37.50435,127.02505"],
        header="station,latitude,longitude",
    )
    output = tmp_path / "result.csv"
    assert main(["batch", "--input", str(source), "--output", str(output), "--sleep", "0"]) == EXIT_OK
    rows = list(csv.DictReader(output.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0]["station"] == "KRC01"
    assert rows[0]["PNU"] == "1168010100108080000"


def test_batch_records_bad_row_and_continues(tmp_path):
    source = write_csv(
        tmp_path / "in.csv",
        ["KRC01,37.50435,127.02505", "KRC02,없음,127.0", "KRC03,37.7519,128.8761"],
    )
    output = tmp_path / "result.csv"
    assert main(["batch", "--input", str(source), "--output", str(output), "--sleep", "0"]) == EXIT_OK
    rows = list(csv.DictReader(output.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 3
    assert "[오류]" in rows[1]["비고"]
    assert rows[2]["소유구분"] == "국유지"
    assert rows[2]["국가기관구분"] == "중앙부처"


def test_batch_limit_and_missing_column(tmp_path, capsys):
    source = write_csv(
        tmp_path / "in.csv",
        ["KRC01,37.50435,127.02505", "KRC02,37.7519,128.8761"],
    )
    output = tmp_path / "result.csv"
    assert main(
        ["batch", "--input", str(source), "--output", str(output), "--sleep", "0", "--limit", "1"]
    ) == EXIT_OK
    rows = list(csv.DictReader(output.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 1

    assert main(["batch", "--input", str(source), "--lat-col", "LAT", "--sleep", "0"]) == EXIT_INPUT
    assert "'LAT' 컬럼이 없습니다" in capsys.readouterr().err


def test_batch_missing_input_file(tmp_path, capsys):
    assert main(["batch", "--input", str(tmp_path / "nope.csv")]) == EXIT_INPUT
    assert "입력 파일을 찾을 수 없습니다" in capsys.readouterr().err


def test_batch_mixed_crs_column(tmp_path):
    source = write_csv(
        tmp_path / "in.csv",
        ["KRC01,37.50435,127.02505,wgs84", "KRC02,37.50435,127.02505,tokyo"],
        header="관측소코드,위도,경도,좌표계",
    )
    output = tmp_path / "result.csv"
    assert main(["batch", "--input", str(source), "--output", str(output), "--sleep", "0"]) == EXIT_OK
    rows = list(csv.DictReader(output.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0]["좌표계"] == "wgs84"
    assert rows[0]["PNU"] == "1168010100108080000"
    assert rows[1]["좌표계"] == "tokyo"
    assert rows[1]["지번주소"].startswith(MOCK_LABEL)
    assert "동경측지계" in rows[1]["비고"]


def test_root_help_lists_commands_and_options():
    text = build_parser().format_help()
    for token in (
        "point",
        "batch",
        "pnu",
        "search",
        "check",
        "--provider",
        "--crs",
        "--nearby",
        "--crs-col",
        "--with-road",
        "국가기관구분",
        "tokyo",
        ".env.example",
    ):
        assert token in text


def test_point_help_describes_crs_and_nearby():
    parser = build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    text = subparsers.choices["point"].format_help()
    assert "--lat" in text
    assert "--crs" in text
    assert "--nearby" in text
    assert "동경측지계" in text
