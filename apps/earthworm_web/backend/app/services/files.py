from __future__ import annotations

from pathlib import Path

from .env import bash_path, parsed_core

READONLY_GLOBAL = "earthworm_global.d"


class PathDenied(ValueError):
    pass


def is_shell_script(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".bash") or name.endswith(".sh") or name == "ew_linux.bash"


def _roots() -> dict[str, Path]:
    env = parsed_core()
    tree = Path(env["EW_HOME"]) / env["EW_VERSION"]
    return {
        "params": Path(env["EW_PARAMS"]).resolve(),
        "environment": (tree / "environment").resolve(),
        "bash": bash_path().resolve().parent,
    }


def resolve_file(root: str, rel: str) -> Path:
    if root not in {"params", "environment"}:
        raise PathDenied("root 는 params 또는 environment")
    if rel is None or rel == "":
        raise PathDenied("path 가 필요합니다")
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise PathDenied("상대 경로만 허용합니다")
    base = _roots()[root]
    path = (base / rel).resolve()
    if base not in path.parents and path != base:
        raise PathDenied("허용된 디렉터리 밖입니다")
    return path


def _readonly(path: Path, root: str) -> bool:
    if is_shell_script(path):
        return True
    return path.name == READONLY_GLOBAL and root == "params"


def list_tree(root: str) -> list[dict]:
    base = _roots()[root]
    if not base.is_dir():
        return []
    items = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(base))
        items.append({"path": rel, "size": p.stat().st_size, "readonly": _readonly(p, root)})
    return items


def read_file(root: str, rel: str) -> dict:
    path = resolve_file(root, rel)
    if not path.is_file():
        raise FileNotFoundError(rel)
    return {
        "root": root,
        "path": rel,
        "content": path.read_text(encoding="utf-8", errors="replace"),
        "readonly": _readonly(path, root),
    }


def write_file(root: str, rel: str, content: str, *, allow_global: bool = False) -> dict:
    path = resolve_file(root, rel)
    if is_shell_script(path):
        raise PathDenied("셸 스크립트는 파일 편집으로 저장할 수 없습니다")
    if path.name == READONLY_GLOBAL and not allow_global:
        raise PathDenied("earthworm_global.d 는 기본 읽기 전용입니다")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        from datetime import datetime, timezone

        bak = path.with_name(
            path.name + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        )
        bak.write_bytes(path.read_bytes())
    path.write_text(content, encoding="utf-8")
    return {"root": root, "path": rel, "saved": True}
