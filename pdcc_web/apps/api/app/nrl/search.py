from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..cache import get_redis
from ..config import settings
from ..models import NrlAlias, NrlExcluded
from .client import NrlError, get_nrl_client, mark_nrl_using_cache, nrl_mode
from .questions import as_list


def _names(nodes: list) -> list[str]:
    out: list[str] = []
    for node in nodes:
        name = node.get("name") if isinstance(node, dict) else None
        if name:
            out.append(str(name))
    return out


def manufacturer_names(element: str) -> list[str]:
    data = get_nrl_client().catalog(level="manufacturer", element=element)
    names: list[str] = []
    for el in as_list(data.get("NRLCatalog", {}).get("element")):
        names.extend(_names(as_list(el.get("manufacturer"))))
    return names


def catalog_index(element: str) -> list[dict[str, str]]:
    redis = get_redis()
    key = f"pdcc:nrl:index:{element}"
    stale: list[dict[str, str]] | None = None
    offline = nrl_mode() == "offline"
    if not offline:
        try:
            raw = redis.get(key)
            if raw:
                return json.loads(raw)
            raw_stale = redis.get(f"{key}:stale")
            if raw_stale:
                stale = json.loads(raw_stale)
        except Exception:
            stale = None
    try:
        rows: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for manufacturer in manufacturer_names(element):
            rows.append({"manufacturer": manufacturer, "model": "", "detail": ""})
            seen.add((manufacturer, ""))
        data = get_nrl_client().catalog(level="model", element=element)
        for el in as_list(data.get("NRLCatalog", {}).get("element")):
            for mfr in as_list(el.get("manufacturer")):
                mfr_name = str(mfr.get("name") or "")
                if not mfr_name:
                    continue
                detail = str(mfr.get("detail") or "")
                if (mfr_name, "") not in seen:
                    rows.append({"manufacturer": mfr_name, "model": "", "detail": detail})
                    seen.add((mfr_name, ""))
                for model in as_list(mfr.get("model")):
                    if not isinstance(model, dict) or not model.get("name"):
                        continue
                    name = str(model["name"])
                    key_row = (mfr_name, name)
                    if key_row in seen:
                        continue
                    seen.add(key_row)
                    rows.append(
                        {
                            "manufacturer": mfr_name,
                            "model": name,
                            "detail": detail + " " + str(model.get("detail") or ""),
                        }
                    )
    except NrlError:
        if stale is not None:
            mark_nrl_using_cache(redis)
            return stale
        raise
    if offline:
        return rows
    try:
        redis.set(key, json.dumps(rows), ex=settings.nrl_cache_ttl_sec)
        redis.set(f"{key}:stale", json.dumps(rows), ex=30 * 24 * 3600)
    except Exception:
        pass
    return rows


def _excluded_hit(db: Session, query: str) -> dict | None:
    q = query.strip().lower()
    rows = db.scalars(select(NrlExcluded)).all()
    for row in rows:
        if q == row.query.lower() or q == row.name.lower() or row.query.lower() in q:
            return {"name": row.name, "message": row.message, "query": row.query}
    return None


def search_nrl(db: Session, *, query: str, element: str) -> dict[str, Any]:
    text = query.strip()
    if len(text) < 2:
        return {"query": text, "hits": [], "excluded": None, "message": "검색어는 2자 이상입니다"}
    excluded = _excluded_hit(db, text)
    if excluded:
        return {"query": text, "hits": [], "excluded": excluded, "message": excluded["message"]}
    q = text.lower()
    aliases = db.scalars(select(NrlAlias)).all()
    alias_mfrs: set[str] = set()
    for alias in aliases:
        if q == alias.query.lower() or alias.query.lower() in q:
            alias_mfrs.add(alias.manufacturer.lower())
    index = catalog_index(element)
    hits: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in index:
        mfr = row["manufacturer"]
        model = row.get("model") or ""
        blob = f"{mfr} {model}".lower()
        via = "catalog"
        matched = q in blob
        if mfr.lower() in alias_mfrs:
            matched = True
            via = "alias"
            if model:
                # alias without a model should highlight the manufacturer row, not every model
                continue
        if not matched:
            continue
        key = (mfr, model)
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            {
                "element": element,
                "manufacturer": mfr,
                "model": model or None,
                "via": via,
            }
        )
    hits.sort(key=lambda item: (item["manufacturer"], item["model"] or ""))
    message = None if hits else "일치하는 장비가 없습니다. 별칭 또는 모델명으로 다시 검색하세요."
    return {"query": text, "hits": hits, "excluded": None, "message": message}
