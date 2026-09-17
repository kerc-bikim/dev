"""명령줄 진입점."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, report
from .batch import CRS_ALIASES, LAT_ALIASES, LON_ALIASES, detect_column, detect_optional_column, read_rows, run_batch
from .cache import build_cache
from .config import Settings
from .errors import EXIT_AUTH, EXIT_NETWORK, EXIT_OK, EXIT_QUOTA, EXIT_TLS, InputError, LatlonError
from .logutil import configure_logging
from .providers import build_provider
from .providers.vworld import DATA_URL, VWorldProvider
from .service import LandLookupService, LookupOptions
from .tls import CHECK_AUTH, CHECK_OK, CHECK_QUOTA, CHECK_TLS_FAILED, check_connection

DESCRIPTION = """\
위도/경도로 그 좌표가 속한 필지의 지번과 토지 정보를 조회합니다.

조회: 지번주소, PNU, 지목, 면적, 소유구분, 국가기관구분, 거주지구분,
공유인수, 소유권변동원인·일자, 공시지가, 용도지역, 토지이용상황.

비조회: 소유자 성명·주소(공개 API 미제공). 등기사항증명서로 안내합니다.

기본 제공자는 mock(키 없이 샘플/합성). 실제 조회는 .env에 키를 넣고
--provider vworld. 옵션 설명은 아래와 각 명령의 -h를 보세요.
"""

EPILOG = """\
공통 옵션 (모든 명령)
  --provider {mock,vworld}  제공자. 기본값은 LATLON_PROVIDER, 없으면 mock
  --crs {wgs84,tokyo}       입력 좌표 기준. GPS·스마트폰은 wgs84(기본)
                            구 지적·종이 지도는 tokyo(동경측지계/Bessel)
  --year YEAR               토지특성 기준연도. 생략 시 올해부터 역순 탐색
  --no-cache                응답 캐시를 쓰지 않음
  -v, -vv                   로그. -v 조회 과정, -vv 요청·파라미터 상세
  -h, --help                도움말
  --version                 버전

point
  --lat LAT --lon LON       위도·경도 (필수)
  --nearby [M]              주변 필지 (미터). 값 생략 시 300
  --with-road               도로명주소도 조회
  --json / --csv            출력 형식. 기본은 사람이 읽는 표

batch
  --input PATH              입력 CSV (필수, UTF-8/UTF-8 BOM)
  --output PATH             출력 CSV. 생략 시 표준출력, UTF-8 BOM
  --lat-col / --lon-col     좌표 컬럼명. 생략 시 위도/경도/lat/lon 등
  --crs-col NAME            행별 좌표계 컬럼. 생략 시 좌표계/crs/datum
  --with-road               도로명주소도 조회
  --sleep SEC               요청 간격(초). 기본 0.2
  --limit N                 상위 N행만 처리

pnu
  --pnu PNU                 19자리 필지고유번호 (필수)
  --json / --csv            출력 형식

search
  --query TEXT              지번 주소 (필수)
  --lat LAT --lon LON       있으면 그 점과의 거리도 표시
  --json                    JSON으로 출력

예
  python -m latlon_converter point --lat 37.50435 --lon 127.02505
  python -m latlon_converter point --lat 37.968352 --lon 124.645289 --crs tokyo --provider vworld
  python -m latlon_converter batch --input examples/stations_sample.csv --output out/result.csv
  python -m latlon_converter search --query "인천광역시 옹진군 백령면 가을리 853"
  python -m latlon_converter pnu --pnu 2872033023108530000 --provider vworld
  python -m latlon_converter check

환경변수는 .env.example, 자세한 설명은 README.md 를 보세요.
명령별 상세 옵션은  latlon_converter <명령> -h  로 확인합니다.
"""


def _korean_help_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="help", help="도움말을 보고 종료")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="latlon_converter",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        parents=[_korean_help_parser()],
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}", help="버전을 출력하고 종료")
    parser._positionals.title = "명령"
    parser._optionals.title = "전역 옵션"

    common = argparse.ArgumentParser(add_help=False, parents=[_korean_help_parser()])
    common.add_argument(
        "--provider",
        choices=("mock", "vworld"),
        help="조회 제공자. 기본값은 환경변수 LATLON_PROVIDER, 없으면 mock",
    )
    common.add_argument("--year", type=int, metavar="YEAR", help="토지특성 기준연도. 생략 시 올해부터 역순 탐색")
    common.add_argument("--no-cache", action="store_true", help="응답 캐시를 쓰지 않음")
    common.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="로그를 자세히 출력. -v 조회 과정, -vv 요청/응답 상세",
    )
    common.add_argument(
        "--crs",
        choices=("wgs84", "tokyo"),
        default="wgs84",
        help="입력 좌표 기준. GPS는 wgs84(기본), 구 지적은 tokyo(동경측지계/Bessel)",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{point,batch,pnu,search,check}",
        title="명령",
    )

    point = subparsers.add_parser(
        "point",
        parents=[common],
        add_help=False,
        help="좌표 한 건 조회",
        description="위도·경도로 필지 지번과 토지 정보를 조회합니다. GPS는 --crs wgs84, 구 지적은 --crs tokyo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    point.add_argument("--lat", type=float, required=True, help="위도")
    point.add_argument("--lon", type=float, required=True, help="경도")
    point.add_argument("--with-road", action="store_true", help="도로명주소도 조회 (지오코더 추가 호출)")
    point.add_argument(
        "--nearby",
        nargs="?",
        const=300.0,
        type=float,
        metavar="M",
        help="주변 필지도 조회 (미터). 값 생략 시 300",
    )
    output = point.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="JSON으로 출력")
    output.add_argument("--csv", action="store_true", help="CSV 한 행으로 출력")

    batch = subparsers.add_parser(
        "batch",
        parents=[common],
        add_help=False,
        help="CSV 일괄 조회",
        description=(
            "CSV의 위도·경도 컬럼을 읽어 한 행씩 조회합니다. "
            "한 파일에 GPS와 구 지적이 섞여 있으면 좌표계 컬럼을 넣으세요."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    batch.add_argument("--input", required=True, metavar="PATH", help="입력 CSV 경로 (UTF-8 또는 UTF-8 BOM)")
    batch.add_argument("--output", metavar="PATH", help="출력 CSV 경로. 생략 시 표준출력, UTF-8 BOM")
    batch.add_argument("--lat-col", metavar="NAME", help=f"위도 컬럼명. 생략 시 자동 인식: {', '.join(LAT_ALIASES)}")
    batch.add_argument("--lon-col", metavar="NAME", help=f"경도 컬럼명. 생략 시 자동 인식: {', '.join(LON_ALIASES)}")
    batch.add_argument(
        "--crs-col",
        metavar="NAME",
        help=f"행별 좌표계 컬럼명. 생략 시 자동 인식: {', '.join(CRS_ALIASES)}",
    )
    batch.add_argument("--with-road", action="store_true", help="도로명주소도 조회 (지오코더 추가 호출)")
    batch.add_argument("--sleep", type=float, default=0.2, metavar="SEC", help="요청 간격(초). 기본 0.2")
    batch.add_argument("--limit", type=int, metavar="N", help="상위 N행만 처리")

    pnu = subparsers.add_parser(
        "pnu",
        parents=[common],
        add_help=False,
        help="PNU로 직접 조회",
        description="필지고유번호(PNU) 19자리로 토지임야·소유·특성 정보를 조회합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pnu.add_argument("--pnu", required=True, metavar="PNU", help="19자리 필지고유번호")
    pnu_output = pnu.add_mutually_exclusive_group()
    pnu_output.add_argument("--json", action="store_true", help="JSON으로 출력")
    pnu_output.add_argument("--csv", action="store_true", help="CSV 한 행으로 출력")

    search = subparsers.add_parser(
        "search",
        parents=[common],
        add_help=False,
        help="지번 주소로 좌표 검색",
        description="지번 주소로 좌표 후보를 찾습니다. 연속지적도 결과와 대조할 때 씁니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    search.add_argument("--query", required=True, metavar="TEXT", help="지번 주소. 예: 인천광역시 옹진군 백령면 가을리 853")
    search.add_argument("--lat", type=float, help="대조할 위도. --lon 과 함께 지정하면 거리도 표시")
    search.add_argument("--lon", type=float, help="대조할 경도. --lat 과 함께 지정")
    search.add_argument("--json", action="store_true", help="JSON으로 출력")

    subparsers.add_parser(
        "check",
        parents=[common],
        add_help=False,
        help="인증서·인증키 설정과 서버 연결을 점검",
        description="조회는 하지 않고 TLS 인증서와 인증키 설정을 점검합니다. 키가 없어도 인증서 검증 여부는 확인할 수 있습니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    return parser


def _build_service(args: argparse.Namespace) -> tuple[LandLookupService, object]:
    settings = Settings.from_env()
    if args.provider:
        settings.provider = args.provider

    cache = build_cache(settings.cache_db, settings.cache_ttl_days, enabled=not args.no_cache)
    if settings.provider == "mock":
        print(
            "[알림] mock 제공자로 실행 중입니다. 실제 조회는 VWORLD_API_KEY 설정 후 "
            "--provider vworld 로 실행하세요.",
            file=sys.stderr,
        )
    # vworld만 캐시를 쓴다. mock은 파일을 읽어 재생하므로 캐시할 게 없다.
    provider = (
        VWorldProvider(settings, cache=cache)
        if settings.provider == "vworld"
        else build_provider(settings)
    )
    return LandLookupService(provider), cache


def _run_check(args: argparse.Namespace) -> int:
    """TLS 인증서와 인증키 설정을 점검한다. 조회는 하지 않는다."""
    settings = Settings.from_env()
    if args.provider:
        settings.provider = args.provider

    check = check_connection(settings, DATA_URL)
    print(report.render_connection_check(settings, check))
    return _check_exit_code(check, settings)


def _check_exit_code(check, settings: Settings) -> int:
    if check.status == CHECK_TLS_FAILED:
        return EXIT_TLS
    if check.status == CHECK_QUOTA:
        return EXIT_QUOTA
    # 인증키를 아예 넣지 않았다면 키 오류는 예상된 결과이므로 성공으로 본다.
    if check.status == CHECK_AUTH:
        return EXIT_AUTH if settings.api_key else EXIT_OK
    if check.status == CHECK_OK:
        return EXIT_OK
    return EXIT_NETWORK


def _nearby_meters(args: argparse.Namespace) -> float | None:
    value = getattr(args, "nearby", None)
    if value in (None, 0):
        return None
    return float(value)


def _emit_single(args: argparse.Namespace, result) -> None:
    if args.json:
        print(report.render_json(result))
    elif args.csv:
        report.write_csv(sys.stdout, [({}, result)])
    else:
        print(report.render_table(result))


def _emit_search(args: argparse.Namespace, service: LandLookupService) -> None:
    if (args.lat is None) ^ (args.lon is None):
        raise InputError("--lat 와 --lon 은 함께 지정해야 합니다")
    hits = service.search_address(args.query, lat=args.lat, lon=args.lon)
    if args.json:
        print(report.render_search_json(hits, args.query))
    else:
        print(report.render_search(hits, args.query))


def _run_batch(args: argparse.Namespace, service: LandLookupService, options: LookupOptions) -> None:
    fieldnames, rows = read_rows(args.input)
    lat_col = detect_column(fieldnames, args.lat_col, LAT_ALIASES, "위도")
    lon_col = detect_column(fieldnames, args.lon_col, LON_ALIASES, "경도")
    crs_col = detect_optional_column(fieldnames, args.crs_col, CRS_ALIASES, "좌표계")
    crs_note = f" · 좌표계 컬럼 '{crs_col}'" if crs_col else ""
    print(f"입력 {len(rows)}행 · 위도 컬럼 '{lat_col}' · 경도 컬럼 '{lon_col}'{crs_note}", file=sys.stderr)

    results = run_batch(
        service,
        rows,
        lat_col,
        lon_col,
        options=options,
        sleep=args.sleep,
        limit=args.limit,
        crs_col=crs_col,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
            written = report.write_csv(handle, results)
        print(f"{written}행을 {output_path}에 저장했습니다", file=sys.stderr)
    else:
        report.write_csv(sys.stdout, results)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(getattr(args, "verbose", 0) or 0)

    cache = None
    try:
        if args.command == "check":
            return _run_check(args)

        service, cache = _build_service(args)
        options = LookupOptions(
            stdr_year=args.year,
            with_road=getattr(args, "with_road", False),
            nearby_m=_nearby_meters(args),
            crs=getattr(args, "crs", "wgs84"),
        )

        if args.command == "point":
            _emit_single(args, service.lookup_point(args.lat, args.lon, options))
        elif args.command == "pnu":
            _emit_single(args, service.lookup_pnu(args.pnu, options))
        elif args.command == "search":
            _emit_search(args, service)
        else:
            _run_batch(args, service, options)
    except LatlonError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("중단되었습니다", file=sys.stderr)
        return 130
    finally:
        if cache is not None:
            cache.close()

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
