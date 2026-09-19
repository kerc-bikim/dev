"""CSV 일괄 등록 파서와 수식 주입 차단."""
from __future__ import annotations

from app.api.csv_import import looks_like_formula, parse_stations_csv


CSV_HEADER = "networkCode,stationCode,name,hostname,credentialReference,latitude,elevationM"


class Test수식주입:
    def test_등호로_시작하는_값은_수식이다(self):
        assert looks_like_formula("=cmd|' /C calc'!A0") is True

    def test_음수_숫자는_수식이_아니다(self):
        assert looks_like_formula("-12.5") is False

    def test_일반_이름은_통과한다(self):
        assert looks_like_formula("설악산") is False


class TestCsv파서:
    def test_정상_행을_읽는다(self):
        text = CSV_HEADER + "\nKS,A01,설악,10.1.2.3,env:SOH_DEVICE_PW_A01,38.1,120\n"
        result = parse_stations_csv(text)
        assert result.errors == []
        assert len(result.rows) == 1
        row = result.rows[0]
        assert row.station_code == "A01"
        assert row.network_code == "KS"
        assert row.hostname == "10.1.2.3"
        assert row.credential_reference == "env:SOH_DEVICE_PW_A01"
        assert row.elevation_m == 120
        assert row.data_source_uri is None

    def test_데이터서버_URI열을_읽는다(self):
        text = (
            "networkCode,stationCode,name,dataSourceUri\n"
            "KS,A01,설악,https://10.0.0.8/fdsnws/availability/1/query?net=KS&sta=A01&format=json\n"
        )
        result = parse_stations_csv(text)
        assert result.errors == []
        assert result.rows[0].data_source_uri.startswith("https://10.0.0.8/")

    def test_수식_행만_실패하고_나머지는_남는다(self):
        text = (
            CSV_HEADER
            + "\nKS,A01,설악,10.1.2.3,env:SOH_PW_A01,38.1,120\n"
            + "KS,A02,=HYPERLINK(1),10.1.2.4,env:SOH_PW_A02,38.2,80\n"
            + "KS,A03,속초,10.1.2.5,env:SOH_PW_A03,38.3,10\n"
        )
        result = parse_stations_csv(text)
        assert [row.station_code for row in result.rows] == ["A01", "A03"]
        assert len(result.errors) == 1
        assert result.errors[0].row == 3

    def test_비밀번호_평문_참조는_거절한다(self):
        text = CSV_HEADER + "\nKS,A01,설악,10.1.2.3,super-secret,38.1,120\n"
        result = parse_stations_csv(text)
        assert result.rows == []
        assert result.errors[0].field == "credentialReference"

    def test_파일_안_중복은_둘째_행만_실패한다(self):
        text = (
            "networkCode,stationCode,name\n"
            "KS,A01,하나\n"
            "KS,A01,둘\n"
            "KS,A02,셋\n"
        )
        result = parse_stations_csv(text)
        assert [row.station_code for row in result.rows] == ["A01", "A02"]
        assert result.errors[0].row == 3

    def test_필수_열이_없으면_전체_실패다(self):
        result = parse_stations_csv("hostname,port\n10.0.0.1,80\n")
        assert result.rows == []
        assert result.errors[0].row == 0
