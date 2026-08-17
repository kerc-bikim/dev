"""엑셀 템플릿 생성 및 파일 변환 CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import seed_catalog
from .crud import export_stationxml_bytes, import_hierarchy
from .db import get_session, init_db
from .errors import AppError
from .excel_io import read_excel, write_excel, write_template_file
from .seed_io import SEED_SUFFIXES, export_dataless_bytes, looks_like_seed_name, read_seed
from .xml_io import read_stationxml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="엑셀/StationXML/SEED 메타데이터 변환")
    parser.add_argument(
        "--write-template", metavar="PATH", help="드롭다운이 있는 엑셀 템플릿 저장"
    )
    parser.add_argument("input", nargs="?", help="입력 엑셀, StationXML 또는 dataless SEED")
    parser.add_argument("-o", "--output", help="출력 StationXML, 엑셀 또는 SEED 경로")
    parser.add_argument(
        "--replace-all", action="store_true", help="기존 DB 목록을 지우고 가져오기"
    )
    parser.add_argument(
        "--apply-nrl", action="store_true", help="카탈로그 NRL 키로 응답을 붙여 저장"
    )
    args = parser.parse_args(argv)

    init_db()
    session = get_session()
    try:
        seed_catalog(session)
        if args.write_template:
            path = Path(args.write_template)
            write_template_file(path, session)
            print(f"템플릿을 저장했습니다: {path}")
            return 0
        if not args.input:
            parser.error("입력 파일이 필요합니다 (또는 --write-template)")
        src = Path(args.input)
        suffix = src.suffix.lower()
        if suffix in {".xml", ".stationxml"}:
            hierarchy = read_stationxml(src, session)
            source = "xml"
        elif looks_like_seed_name(src.name):
            hierarchy = read_seed(src, session)
            source = "seed"
        else:
            hierarchy = read_excel(src)
            source = "excel"
        result = import_hierarchy(
            session,
            hierarchy,
            replace_all=args.replace_all,
            source=source,
            actor="cli",
        )
        for warn in result.get("warnings") or []:
            print(f"경고: {warn}")
        print(f"가져오기 완료: 추가 {result['created']} / 수정 {result['updated']}")
        if args.apply_nrl:
            from .crud import apply_nrl, list_channels

            for ch in list_channels(session):
                try:
                    apply_nrl(session, ch.id, "cli")
                    print(
                        f"NRL 적용: {ch.station.network.code}.{ch.station.code}.{ch.channel}"
                    )
                except Exception as exc:  # noqa: BLE001 - ObsPy NRL 오류는 채널별로 건너뜀
                    print(f"NRL 실패 ({ch.channel}): {exc}")
        out = Path(args.output) if args.output else src.with_suffix(".xml")
        out_suffix = out.suffix.lower()
        if out_suffix in {".xlsx", ".xls"}:
            out.write_bytes(write_excel(session))
        elif out_suffix in SEED_SUFFIXES:
            try:
                data, warnings = export_dataless_bytes(session)
            except AppError as exc:
                for item in exc.errors:
                    print(item.get("reason") or exc.message, file=sys.stderr)
                if not exc.errors:
                    print(exc.message, file=sys.stderr)
                return 1
            for warn in warnings:
                print(f"경고: {warn}")
            out.write_bytes(data)
        else:
            out.write_bytes(export_stationxml_bytes(session))
        print(f"저장: {out}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
