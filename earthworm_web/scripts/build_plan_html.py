"""Convert plan.md to plan.html."""
from __future__ import annotations

import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
MD_PATHS = (ROOT / "plan.md", ROOT / "plan_priority.md", ROOT / "plan_mvp.md")
HTML_PATH = ROOT / "plan.html"

CSS = """
:root {
  --bg: #f6f4ef;
  --surface: #fffdf8;
  --ink: #1c2430;
  --muted: #5a6570;
  --line: #d7d2c8;
  --accent: #0b4f6e;
  --accent-soft: #d8e6ee;
  --code-bg: #eef2f4;
  --table-head: #e8eef3;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: "Pretendard", "Noto Sans KR", "Segoe UI", sans-serif;
  color: var(--ink);
  background:
    radial-gradient(1200px 600px at 10% -10%, #e7eef3 0%, transparent 55%),
    radial-gradient(900px 500px at 100% 0%, #efe8dc 0%, transparent 50%),
    var(--bg);
  line-height: 1.65;
}
.wrap {
  max-width: 960px;
  margin: 0 auto;
  padding: 2.5rem 1.25rem 4rem;
}
header.doc-header {
  border-bottom: 2px solid var(--accent);
  padding-bottom: 1.25rem;
  margin-bottom: 2rem;
}
header.doc-header .eyebrow {
  color: var(--accent);
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  margin: 0 0 0.4rem;
}
h1 {
  font-size: clamp(1.6rem, 3vw, 2.1rem);
  line-height: 1.25;
  margin: 0 0 0.75rem;
}
.meta {
  color: var(--muted);
  font-size: 0.95rem;
}
article h1 { display: none; }
article h2 {
  margin-top: 2.4rem;
  padding-top: 0.6rem;
  border-top: 1px solid var(--line);
  font-size: 1.35rem;
  color: var(--accent);
}
article h3 {
  margin-top: 1.6rem;
  font-size: 1.1rem;
}
article h4 { margin-top: 1.2rem; }
p, li { font-size: 0.98rem; }
a { color: var(--accent); }
hr {
  border: 0;
  border-top: 1px solid var(--line);
  margin: 2rem 0;
}
table {
  width: 100%;
  border-collapse: collapse;
  background: var(--surface);
  box-shadow: 0 1px 0 rgba(0,0,0,0.03);
  margin: 1rem 0 1.4rem;
  font-size: 0.92rem;
}
th, td {
  border: 1px solid var(--line);
  padding: 0.55rem 0.7rem;
  vertical-align: top;
  text-align: left;
}
th { background: var(--table-head); }
code, pre {
  font-family: "JetBrains Mono", "Consolas", monospace;
  font-size: 0.86rem;
}
code {
  background: var(--code-bg);
  padding: 0.1em 0.35em;
  border-radius: 4px;
}
pre {
  background: #1c2430;
  color: #e8eef2;
  padding: 1rem 1.1rem;
  border-radius: 10px;
  overflow-x: auto;
}
pre code { background: transparent; color: inherit; padding: 0; }
.diagram {
  margin: 1rem 0 1.4rem;
}
iframe.diagram {
  display: block;
  width: 100%;
  height: 640px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #f5f5f5;
}
figure.diagram {
  margin: 1rem 0 1.4rem;
}
figure.diagram figcaption {
  margin-top: 0.4rem;
  font-size: 0.82rem;
  color: var(--muted);
}
blockquote {
  margin: 1rem 0;
  padding: 0.6rem 1rem;
  border-left: 4px solid var(--accent);
  background: var(--accent-soft);
}
footer {
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 0.85rem;
}
@media (max-width: 640px) {
  .wrap { padding: 1.5rem 0.9rem 3rem; }
  table { display: block; overflow-x: auto; }
}
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Earthworm Web Control — 계획서</title>
  <style>{css}</style>
</head>
<body>
  <div class="wrap">
    <header class="doc-header">
      <p class="eyebrow">Earthworm · Web Control Plan</p>
      <h1>Earthworm Web Control — 계획서</h1>
      <p class="meta">v8.0b17 · FastAPI 백엔드 + React 프론트엔드 · 우선 모듈 · 구성 보드 · 모노레포</p>
    </header>
    <article>
{body}
    </article>
    <footer>
      Generated from <code>plan.md</code> + <code>plan_priority.md</code> + <code>plan_mvp.md</code>.
    </footer>
  </div>
</body>
</html>
"""


def md_to_html(text: str) -> str:
    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists", "toc"],
    )
    return embed_diagrams(html)


DIAGRAM_HEIGHTS = {
    "setup-phases": 640,
    "setup-sequence": 700,
    "architecture": 620,
    "start-sequence": 640,
    "clone-sequence": 660,
    "sniff-sequence": 700,
    "stack-layers": 500,
    "module-families": 640,
    "compose-board": 680,
    "instance-fleet": 620,
    "monorepo": 600,
    "compose-apply": 660,
    "phase-roadmap": 600,
    "mvp-scope": 620,
}


def embed_diagrams(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        href, title = match.group(1), match.group(2)
        slug = Path(href).stem
        height = DIAGRAM_HEIGHTS.get(slug, 600)
        return (
            f'<figure class="diagram">'
            f'<iframe class="diagram" src="{href}" title="{title}" loading="lazy" '
            f'style="height:{height}px"></iframe>'
            f'<figcaption><a href="{href}">{title}</a> · '
            f'<a href="https://github.com/cathrynlavery/diagram-design">diagram-design</a></figcaption>'
            f"</figure>"
        )

    return re.sub(
        r'<a href="(diagrams/[^"]+\.html)">([^<]+)</a>',
        repl,
        html,
    )


def load_markdown() -> str:
    chunks: list[str] = []
    for i, path in enumerate(MD_PATHS):
        text = path.read_text(encoding="utf-8")
        if i > 0:
            text = re.sub(r"^# .+\n+", "", text, count=1)
        chunks.append(text.rstrip())
    return "\n\n".join(chunks) + "\n"


def main() -> None:
    md = load_markdown()
    body = md_to_html(md)
    html = TEMPLATE.replace("{css}", CSS).replace("{body}", body)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {HTML_PATH}")


if __name__ == "__main__":
    main()
