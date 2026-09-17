"""명령줄 진입점."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, report
from .batch import LAT_ALIASES, LON_ALIASES, detect_column, read_rows, run_batch
from .cache import build_cache
from .config import Settings
from .errors import EXIT_AUTH, EXIT_NETWORK, EXIT_OK, EXIT_QUOTA, EXIT_TLS, LatlonError
from .providers import build_provider
from .providers.vworld import DATA_URL, VWorldProvider
from .service import LandLookupService, LookupOptions
from .tls import CHECK_AUTH, CHECK_OK, CHECK_QUOTA, CHECK_TLS_FAILED, check_connection

DESCRIPTION = """\
위도/경도로 지번과 토지 정보를 조회합니다.

소유자 성명은 어떤 공개 API로도 제공되지 않으므로 소유구분(개인/국유지/법인 등)과
공유인수까지만 표시하고, 실명은 등기사항증명서로 안내합니다.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="latlon_converter",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--provider", choices=("mock", "vworld"), help="조회 제공자 (기본: LATLON_PROVIDER)")
    common.add_argument("--year", type=int, help="토지특성 기준연도 (기본: 올해부터 역순 탐색)")
    common.add_argument("--no-cache", action="store_true", help="응답 캐시를 쓰지 않음")
    common.add_argument("-v", "--verbose", action="store_true", help="디버그 로그 출력")

    subparsers = parser.add_subparsers(dest="command", required=True)

    point = subparsers.add_parser("point", parents=[common], help="좌표 한 건 조회")
    point.add_argument("--lat", type=float, required=True, help="위도 (WGS84)")
    point.add_argument("--lon", type=float, required=True, help="경도 (WGS84)")
    point.add_argument("--with-road", action="store_true", help="도로명주소도 조회")
    output = point.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="JSON으로 출력")
    output.add_argument("--csv", action="store_true", help="CSV 한 행으로 출력")

    batch = subparsers.add_parser("batch", parents=[common], help="CSV 일괄 조회")
    batch.add_argument("--input", required=True, help="입력 CSV 경로")
    batch.add_argument("--output", help="출력 CSV 경로 (생략 시 표준출력)")
    batch.add_argument("--lat-col", help=f"위도 컬럼명 (기본 자동 인식: {', '.join(LAT_ALIASES)})")
    batch.add_argument("--lon-col", help=f"경도 컬럼명 (기본 자동 인식: {', '.join(LON_ALIASES)})")
    batch.add_argument("--with-road", action="store_true", help="도로명주소도 조회")
    batch.add_argument("--sleep", type=float, default=0.2, help="요청 간격(초), 기본 0.2")
    batch.add_argument("--limit", type=int, help="상위 N행만 처리")

    subparsers.add_parser(
        "check",
        parents=[common],
        help="인증서·인증키 설정과 서버 연결을 점검 (키 없이도 TLS 확인 가능)",
    )

    pnu = subparsers.add_parser("pnu", parents=[common], help="PNU로 직접 조회")
    pnu.add_argument("--pnu", required=True, help="19자리 PNU")
    pnu_output = pnu.add_mutually_exclusive_group()
    pnu_output.add_argument("--json", action="store_true", help="JSON으로 출력")
    pnu_output.add_argument("--csv", action="store_true", help="CSV 한 행으로 출력")

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


def _emit_single(args: argparse.Namespace, result) -> None:
    if args.json:
        print(report.render_json(result))
    elif args.csv:
        report.write_csv(sys.stdout, [({}, result)])
    else:
        print(report.render_table(result))


def _run_batch(args: argparse.Namespace, service: LandLookupService, options: LookupOptions) -> None:
    fieldnames, rows = read_rows(args.input)
    lat_col = detect_column(fieldnames, args.lat_col, LAT_ALIASES, "위도")
    lon_col = detect_column(fieldnames, args.lon_col, LON_ALIASES, "경도")
    print(f"입력 {len(rows)}행 · 위도 컬럼 '{lat_col}' · 경도 컬럼 '{lon_col}'", file=sys.stderr)

    results = run_batch(
        service,
        rows,
        lat_col,
        lon_col,
        options=options,
        sleep=args.sleep,
        limit=args.limit,
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
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cache = None
    try:
        if args.command == "check":
            return _run_check(args)

        service, cache = _build_service(args)
        options = LookupOptions(
            stdr_year=args.year,
            with_road=getattr(args, "with_road", False),
        )

        if args.command == "point":
            _emit_single(args, service.lookup_point(args.lat, args.lon, options))
        elif args.command == "pnu":
            _emit_single(args, service.lookup_pnu(args.pnu, options))
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
