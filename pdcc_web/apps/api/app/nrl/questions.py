from __future__ import annotations

from typing import Any, Iterable


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def question_text(param_key: str, prefixes: Iterable[dict]) -> str:
    for row in prefixes:
        if row.get("description") == param_key:
            question = (row.get("question") or "").strip()
            if question:
                return question
    return param_key.replace("_", " ") + "?"


def prefix_order(prefixes: Iterable[dict]) -> dict[str, int]:
    order: dict[str, int] = {}
    for i, row in enumerate(prefixes):
        desc = row.get("description")
        if isinstance(desc, str) and desc not in order:
            order[desc] = i
    return order


def unique_param_values(configs: list[dict]) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for cfg in configs:
        params = cfg.get("parameters") or {}
        for key, raw in params.items():
            values.setdefault(key, set()).add(str(raw))
    return values


def remaining_configs(configs: list[dict], answers: dict[str, str]) -> list[dict]:
    if not answers:
        return list(configs)
    out = []
    for cfg in configs:
        params = cfg.get("parameters") or {}
        if all(str(params.get(key)) == value for key, value in answers.items()):
            out.append(cfg)
    return out


def build_wizard(
    configs: list[dict],
    answers: dict[str, str],
    prefixes: list[dict],
) -> dict:
    remaining = remaining_configs(configs, answers)
    uniques = unique_param_values(remaining)
    order = prefix_order(prefixes)
    questions: list[dict] = []
    locked: dict[str, str] = {}
    for key, values in uniques.items():
        if key in answers:
            continue
        if len(values) >= 2:
            questions.append(
                {
                    "key": key,
                    "question": question_text(key, prefixes),
                    "options": sorted(values),
                }
            )
        elif len(values) == 1:
            locked[key] = next(iter(values))
    questions.sort(key=lambda q: (order.get(q["key"], 10_000), q["key"]))
    matches = [
        {
            "instconfig": cfg.get("instconfig"),
            "description": cfg.get("description", ""),
            "parameters": cfg.get("parameters") or {},
        }
        for cfg in remaining
    ]
    return {
        "questions": questions,
        "locked": locked,
        "matches": matches,
        "match_count": len(matches),
    }
