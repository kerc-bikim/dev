"""CSV 입력 처리와 파일 인코딩 검증."""

from __future__ import annotations

import pytest

from latlon_converter.batch import CRS_ALIASES, LAT_ALIASES, LON_ALIASES, detect_column, parse_crs, read_rows
from latlon_converter.config import PROJECT_ROOT
from latlon_converter.errors import InputError

SAMPLE_CSV = PROJECT_ROOT / "examples" / "stations_sample.csv"
UTF8_BOM = b"\xef\xbb\xbf"


def test_sample_csv_has_utf8_bom():
    """한국어 윈도우 엑셀은 BOM이 없으면 CP949로 읽어 한글이 깨진다.

    이 파일을 편집하는 도구가 BOM을 지우면 다시 깨지므로 바이트로 확인한다.
    """
    assert SAMPLE_CSV.read_bytes().startswith(UTF8_BOM)


def test_sample_csv_korean_is_readable():
    fieldnames, rows = read_rows(SAMPLE_CSV)
    # BOM이 컬럼명에 섞여 들어가면 '\ufeff관측소코드'가 된다.
    assert fieldnames == ["관측소코드", "관측소명", "위도", "경도", "좌표계"]
    assert len(rows) == 6
    assert rows[0]["관측소코드"] == "KRC01"
    assert rows[0]["관측소명"] == "역삼 도심부지"
    assert rows[0]["좌표계"] == "wgs84"
    assert rows[1]["관측소명"] == "대기리 산지부지"
    assert rows[-1]["관측소코드"] == "BRD01"
    assert rows[-1]["관측소명"] == "백령 가을리"
    assert rows[-1]["좌표계"] == "tokyo"


def test_sample_csv_columns_are_detected():
    fieldnames, _ = read_rows(SAMPLE_CSV)
    assert detect_column(fieldnames, None, LAT_ALIASES, "위도") == "위도"
    assert detect_column(fieldnames, None, LON_ALIASES, "경도") == "경도"
    assert detect_column(fieldnames, None, CRS_ALIASES, "좌표계") == "좌표계"


@pytest.mark.parametrize("bom", [b"", UTF8_BOM])
def test_read_rows_accepts_both_bom_and_plain_utf8(tmp_path, bom):
    path = tmp_path / "in.csv"
    path.write_bytes(bom + "관측소명,위도,경도\n역삼,37.5,127.0\n".encode("utf-8"))

    fieldnames, rows = read_rows(path)
    assert fieldnames == ["관측소명", "위도", "경도"]
    assert rows[0]["관측소명"] == "역삼"


def test_parse_crs_aliases_and_default():
    assert parse_crs("", "wgs84") == "wgs84"
    assert parse_crs("  ", "tokyo") == "tokyo"
    assert parse_crs("WGS84", "tokyo") == "wgs84"
    assert parse_crs("세계측지계", "tokyo") == "wgs84"
    assert parse_crs("동경", "wgs84") == "tokyo"
    assert parse_crs("Bessel", "wgs84") == "tokyo"
    with pytest.raises(InputError, match="알 수 없는 좌표계"):
        parse_crs("katech", "wgs84", line=3)


def test_read_rows_rejects_missing_and_headerless_files(tmp_path):
    with pytest.raises(InputError):
        read_rows(tmp_path / "nope.csv")

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(InputError):
        read_rows(empty)
