from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..models import User
from ..nrl.client import NrlError, get_nrl_client, validate_format, validate_instconfig
from ..nrl.curve import CurveError, eval_response_curve, sample_rate_from_instconfig
from ..nrl.questions import as_list, build_wizard
from ..routers.auth import current_user

router = APIRouter(prefix="/api/nrl", tags=["nrl"])


class WizardIn(BaseModel):
    element: str = Field(min_length=1, max_length=64)
    manufacturer: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    answers: dict[str, str] = Field(default_factory=dict)


def _http(exc: NrlError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _names(nodes: list) -> list[str]:
    out: list[str] = []
    for node in nodes:
        name = node.get("name") if isinstance(node, dict) else None
        if name:
            out.append(str(name))
    return out


@router.get("/elements")
def nrl_elements(_user: User = Depends(current_user)) -> dict:
    try:
        data = get_nrl_client().catalog(level="element")
    except NrlError as exc:
        _http(exc)
    elements = _names(as_list(data.get("NRLCatalog", {}).get("element")))
    return {"elements": elements}


@router.get("/manufacturers")
def nrl_manufacturers(
    element: str = Query(min_length=1),
    _user: User = Depends(current_user),
) -> dict:
    try:
        data = get_nrl_client().catalog(level="manufacturer", element=element)
    except NrlError as exc:
        _http(exc)
    elements = as_list(data.get("NRLCatalog", {}).get("element"))
    manufacturers: list[str] = []
    for el in elements:
        manufacturers.extend(_names(as_list(el.get("manufacturer"))))
    return {"element": element, "manufacturers": manufacturers}


@router.get("/models")
def nrl_models(
    element: str = Query(min_length=1),
    manufacturer: str = Query(min_length=1),
    _user: User = Depends(current_user),
) -> dict:
    try:
        data = get_nrl_client().catalog(
            level="model", element=element, manufacturer=manufacturer
        )
    except NrlError as exc:
        _http(exc)
    models: list[str] = []
    for el in as_list(data.get("NRLCatalog", {}).get("element")):
        for mfr in as_list(el.get("manufacturer")):
            models.extend(_names(as_list(mfr.get("model"))))
    return {"element": element, "manufacturer": manufacturer, "models": models}


def _configurations(catalog: dict) -> list[dict]:
    configs: list[dict] = []
    for el in as_list(catalog.get("NRLCatalog", {}).get("element")):
        for mfr in as_list(el.get("manufacturer")):
            for model in as_list(mfr.get("model")):
                for cfg in as_list(model.get("configuration")):
                    configs.append(
                        {
                            "instconfig": cfg.get("instconfig"),
                            "description": cfg.get("description", ""),
                            "parameters": cfg.get("parameters") or {},
                        }
                    )
    return configs


@router.post("/wizard")
def nrl_wizard(body: WizardIn, _user: User = Depends(current_user)) -> dict:
    client = get_nrl_client()
    try:
        catalog = client.catalog(
            level="configuration",
            element=body.element,
            manufacturer=body.manufacturer,
            model=body.model,
        )
        prefixes = client.prefix_lookup()
    except NrlError as exc:
        _http(exc)
    result = build_wizard(_configurations(catalog), body.answers, prefixes)
    result.update(
        {
            "element": body.element,
            "manufacturer": body.manufacturer,
            "model": body.model,
            "answers": body.answers,
        }
    )
    return result


@router.get("/combine")
def nrl_combine(
    instconfig: str = Query(min_length=1),
    format: str = Query(default="stationxml-resp", alias="format"),
    _user: User = Depends(current_user),
):
    try:
        payload, content_type = get_nrl_client().combine(
            validate_instconfig(instconfig), validate_format(format)
        )
    except NrlError as exc:
        _http(exc)
    return Response(content=payload, media_type=content_type)


@router.get("/curve")
def nrl_curve(
    instconfig: str = Query(min_length=1),
    output: str = Query(default="VEL"),
    min_freq: float = Query(default=0.001, gt=0),
    max_freq: float | None = Query(default=None, gt=0),
    npts: int = Query(default=200, ge=50, le=1000),
    _user: User = Depends(current_user),
) -> dict:
    try:
        inst = validate_instconfig(instconfig)
        payload, _content_type = get_nrl_client().combine(inst, "stationxml-resp")
        return eval_response_curve(
            payload,
            output=output,
            min_freq=min_freq,
            max_freq=max_freq,
            npts=npts,
            sample_rate=sample_rate_from_instconfig(inst),
            instconfig=inst,
        )
    except CurveError as exc:
        _http(exc)
    except NrlError as exc:
        _http(exc)
