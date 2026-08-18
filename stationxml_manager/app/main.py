from __future__ import annotations

import hmac
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from .audit import to_dict
from .catalog import seed_catalog
from .crud import (
    apply_nrl,
    catalog_to_dict,
    create_catalog_item,
    create_channel,
    create_station,
    delete_catalog_item,
    delete_channel,
    delete_station,
    export_stationxml_bytes,
    get_channel,
    import_hierarchy,
    list_catalog,
    list_channels,
    list_history,
    list_networks,
    list_stations,
    update_catalog_item,
    update_channel,
    update_network,
    update_station,
)
from .db import get_session, init_db
from .errors import AppError, ValidationError
from .excel_io import read_excel, write_excel, write_template
from .models import AuditLog
from .response import (
    eval_response_curve,
    list_response_stages,
    overlay_response_curves,
    parse_ids,
    update_pz_stage,
)
from .seed_io import export_dataless_bytes, looks_like_seed_name, read_seed
from .xml_io import read_stationxml

app = FastAPI(title="StationXML 메타데이터 관리", version="0.1.0")
_cors_origins = [
    value.strip()
    for value in os.getenv(
        "STATIONXML_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if value.strip()
]

_api_key = os.getenv("STATIONXML_API_KEY", "")
_local_clients = {"127.0.0.1", "::1", "testclient"}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except ValueError:
        return default


_max_upload_bytes = _positive_int_env("STATIONXML_MAX_UPLOAD_MB", 20) * 1024 * 1024


@app.middleware("http")
async def protect_api(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method != "OPTIONS":
        supplied_key = request.headers.get("X-API-Key", "")
        if _api_key:
            if not hmac.compare_digest(supplied_key, _api_key):
                return JSONResponse(
                    {"detail": "유효한 API 키가 필요합니다"},
                    status_code=401,
                )
        else:
            client_host = request.client.host if request.client else ""
            proxied = bool(
                request.headers.get("Forwarded")
                or request.headers.get("X-Forwarded-For")
            )
            if client_host not in _local_clients or proxied:
                return JSONResponse(
                    {
                        "detail": (
                            "원격 API 접근이 차단되었습니다. "
                            "서버에 STATIONXML_API_KEY를 설정하세요"
                        )
                    },
                    status_code=403,
                )
    return await call_next(request)


# CORS를 인증 미들웨어 바깥에 두어 401/403에도 브라우저가 오류 본문을 읽게 한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Export-Warnings"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    session = get_session()
    try:
        seed_catalog(session)
    finally:
        session.close()


@app.exception_handler(AppError)
def _app_error(_request: Request, exc: AppError) -> JSONResponse:
    body: dict[str, Any] = {"detail": exc.message}
    if exc.errors:
        body["errors"] = exc.errors
    return JSONResponse(body, status_code=exc.status_code)


@app.exception_handler(IntegrityError)
def _integrity_error(_request: Request, _exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        {"detail": "같은 코드 또는 NSLC/시작시간을 가진 항목이 이미 있습니다"},
        status_code=409,
    )


def _actor(actor: str | None) -> str | None:
    value = (actor or "").strip()
    return value or None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/networks")
def api_list_networks() -> list[dict[str, Any]]:
    session = get_session()
    try:
        return [to_dict(n) for n in list_networks(session)]
    finally:
        session.close()


@app.put("/api/networks/{network_id}")
def api_update_network(
    network_id: int, payload: dict[str, Any], actor: str | None = None
) -> dict[str, Any]:
    session = get_session()
    try:
        return to_dict(update_network(session, network_id, payload, _actor(actor)))
    finally:
        session.close()


@app.get("/api/stations")
def api_list_stations(network_id: int | None = None) -> list[dict[str, Any]]:
    session = get_session()
    try:
        return [to_dict(s) for s in list_stations(session, network_id)]
    finally:
        session.close()


@app.post("/api/stations")
def api_create_station(
    payload: dict[str, Any], actor: str | None = None
) -> dict[str, Any]:
    session = get_session()
    try:
        return to_dict(create_station(session, payload, _actor(actor)))
    finally:
        session.close()


@app.put("/api/stations/{station_id}")
def api_update_station(
    station_id: int, payload: dict[str, Any], actor: str | None = None
) -> dict[str, Any]:
    session = get_session()
    try:
        return to_dict(update_station(session, station_id, payload, _actor(actor)))
    finally:
        session.close()


@app.delete("/api/stations/{station_id}")
def api_delete_station(station_id: int, actor: str | None = None) -> dict[str, str]:
    session = get_session()
    try:
        delete_station(session, station_id, _actor(actor))
        return {"status": "deleted"}
    finally:
        session.close()


@app.get("/api/channels")
def api_list_channels(
    network: str | None = None,
    station: str | None = None,
    channel: str | None = None,
) -> list[dict[str, Any]]:
    session = get_session()
    try:
        return [to_dict(c) for c in list_channels(session, network, station, channel)]
    finally:
        session.close()


@app.post("/api/channels")
def api_create_channel(
    payload: dict[str, Any], actor: str | None = None
) -> dict[str, Any]:
    session = get_session()
    try:
        return to_dict(create_channel(session, payload, _actor(actor)))
    finally:
        session.close()


@app.put("/api/channels/{channel_id}")
def api_update_channel(
    channel_id: int, payload: dict[str, Any], actor: str | None = None
) -> dict[str, Any]:
    session = get_session()
    try:
        return to_dict(update_channel(session, channel_id, payload, _actor(actor)))
    finally:
        session.close()


@app.delete("/api/channels/{channel_id}")
def api_delete_channel(channel_id: int, actor: str | None = None) -> dict[str, str]:
    session = get_session()
    try:
        delete_channel(session, channel_id, _actor(actor))
        return {"status": "deleted"}
    finally:
        session.close()


@app.get("/api/channels/{channel_id}/response-curve")
def api_response_curve(
    channel_id: int,
    output: str = "VEL",
    min_freq: float = 0.001,
    max_freq: float | None = None,
    npts: int = 200,
) -> dict[str, Any]:
    session = get_session()
    try:
        return eval_response_curve(
            get_channel(session, channel_id),
            output=output,
            min_freq=min_freq,
            max_freq=max_freq,
            npts=npts,
        )
    finally:
        session.close()


@app.get("/api/response-curves")
def api_response_curves(
    ids: str,
    output: str = "VEL",
    min_freq: float = 0.001,
    max_freq: float | None = None,
    npts: int = 200,
) -> dict[str, Any]:
    session = get_session()
    try:
        return overlay_response_curves(
            session,
            parse_ids(ids),
            output=output,
            min_freq=min_freq,
            max_freq=max_freq,
            npts=npts,
        )
    finally:
        session.close()


@app.get("/api/channels/{channel_id}/response-stages")
def api_response_stages(channel_id: int) -> dict[str, Any]:
    session = get_session()
    try:
        return list_response_stages(get_channel(session, channel_id))
    finally:
        session.close()


@app.put("/api/channels/{channel_id}/response-stages/{stage_number}")
def api_update_pz_stage(
    channel_id: int,
    stage_number: int,
    payload: dict[str, Any],
    actor: str | None = None,
) -> dict[str, Any]:
    session = get_session()
    try:
        return update_pz_stage(
            session, channel_id, stage_number, payload, _actor(actor)
        )
    finally:
        session.close()


@app.post("/api/channels/{channel_id}/apply-nrl")
def api_apply_nrl(channel_id: int, actor: str | None = None) -> dict[str, Any]:
    session = get_session()
    try:
        return to_dict(apply_nrl(session, channel_id, _actor(actor)))
    finally:
        session.close()


@app.get("/api/catalog")
def api_list_catalog(kind: str | None = None) -> list[dict[str, Any]]:
    session = get_session()
    try:
        rows = list_catalog(session, kind)
        return [catalog_to_dict(r) for r in rows]
    finally:
        session.close()


@app.post("/api/catalog")
def api_create_catalog(
    payload: dict[str, Any], actor: str | None = None
) -> dict[str, Any]:
    session = get_session()
    try:
        row = create_catalog_item(session, payload, _actor(actor))
        return catalog_to_dict(row)
    finally:
        session.close()


@app.put("/api/catalog/{item_id}")
def api_update_catalog(
    item_id: int, payload: dict[str, Any], actor: str | None = None
) -> dict[str, Any]:
    session = get_session()
    try:
        row = update_catalog_item(session, item_id, payload, _actor(actor))
        return catalog_to_dict(row)
    finally:
        session.close()


@app.delete("/api/catalog/{item_id}")
def api_delete_catalog(item_id: int, actor: str | None = None) -> dict[str, str]:
    session = get_session()
    try:
        delete_catalog_item(session, item_id, _actor(actor))
        return {"status": "deleted"}
    finally:
        session.close()


@app.post("/api/import")
async def api_import(
    file: Annotated[UploadFile, File()],
    replace_all: Annotated[bool, Form()] = False,
    confirm_replace: Annotated[bool, Form()] = False,
    actor: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    if replace_all and not confirm_replace:
        raise ValidationError("전체 교체 확인 값이 필요합니다")
    raw = await file.read(_max_upload_bytes + 1)
    if len(raw) > _max_upload_bytes:
        raise ValidationError(
            f"업로드 파일은 {int(_max_upload_bytes / 1024 / 1024)}MB 이하여야 합니다"
        )
    name = (file.filename or "").lower()
    session = get_session()
    try:
        try:
            if name.endswith((".xml", ".stationxml")):
                hierarchy = read_stationxml(BytesIO(raw), session)
                source = "xml"
            elif name.endswith((".xlsx", ".xls")):
                hierarchy = read_excel(BytesIO(raw))
                source = "excel"
            elif looks_like_seed_name(name):
                hierarchy = read_seed(BytesIO(raw), session)
                source = "seed"
            else:
                raise HTTPException(
                    status_code=400,
                    detail="xlsx, StationXML(xml), dataless SEED 파일만 올릴 수 있습니다",
                )
        except (AppError, HTTPException):
            raise
        except Exception as exc:
            raise ValidationError(
                f"파일을 읽지 못했습니다. 형식과 내용을 확인하세요: {exc}"
            ) from exc
        result = import_hierarchy(
            session,
            hierarchy,
            replace_all=replace_all,
            source=source,
            actor=_actor(actor),
        )
        return result
    finally:
        session.close()


@app.get("/api/export/stationxml")
def api_export_xml() -> Response:
    session = get_session()
    try:
        data = export_stationxml_bytes(session)
        return Response(
            content=data,
            media_type="application/xml",
            headers={"Content-Disposition": "attachment; filename=inventory.xml"},
        )
    finally:
        session.close()


@app.get("/api/export/dataless")
def api_export_dataless() -> Response:
    session = get_session()
    try:
        data, warnings = export_dataless_bytes(session)
        headers = {
            "Content-Disposition": "attachment; filename=inventory.dataless",
        }
        if warnings:
            headers["X-Export-Warnings"] = quote(
                json.dumps(warnings, ensure_ascii=True)
            )
        return Response(
            content=data,
            media_type="application/vnd.fdsn.seed",
            headers=headers,
        )
    finally:
        session.close()


@app.get("/api/export/xlsx")
def api_export_xlsx() -> Response:
    session = get_session()
    try:
        data = write_excel(session)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=inventory.xlsx"},
        )
    finally:
        session.close()


@app.get("/api/template.xlsx")
def api_template() -> Response:
    session = get_session()
    try:
        data = write_template(session)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": "attachment; filename=stationxml_template.xlsx"
            },
        )
    finally:
        session.close()


@app.get("/api/history")
def api_history(
    limit: int = Query(200, le=1000), nslc: str | None = None
) -> list[dict[str, Any]]:
    session = get_session()
    try:
        rows: list[AuditLog] = list_history(session, limit=limit, nslc=nslc)
        return [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "source": r.source,
                "actor": r.actor,
                "nslc": r.nslc,
                "before_json": r.before_json,
                "after_json": r.after_json,
                "summary": r.summary,
            }
            for r in rows
        ]
    finally:
        session.close()


_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="ui")
