"""Convert plan.md to plan.html."""
from __future__ import annotations

from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
MD_PATH = ROOT / "plan.md"
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
.mermaid, pre.mermaid {
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--line);
  padding: 1rem;
  border-radius: 10px;
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
  <script type="module">
    import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
    mermaid.initialize({{ startOnLoad: true, theme: "neutral" }});
  </script>
</head>
<body>
  <div class="wrap">
    <header class="doc-header">
      <p class="eyebrow">Earthworm · Web Control Plan</p>
      <h1>Earthworm Web Control — 계획서</h1>
      <p class="meta">v8.0b17 · FastAPI 백엔드 + React 프론트엔드 · 구현 전 확정 계획</p>
    </header>
    <article>
{body}
    </article>
    <footer>
      Generated from <code>plan.md</code>.
    </footer>
  </div>
</body>
</html>
"""


def md_to_html(text: str) -> str:
    parts: list[str] = []
    chunks = text.split("```")
    for i, chunk in enumerate(chunks):
        if i % 2 == 1:
            lang, _, content = chunk.partition("\n")
            lang = lang.strip().lower()
            if lang == "mermaid":
                parts.append(f'<pre class="mermaid">\n{content.strip()}\n</pre>')
            else:
                parts.append(f"```{lang}\n{content}```")
        else:
            parts.append(chunk)
    processed = "".join(parts)
    return markdown.markdown(
        processed,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists", "toc"],
    )


def main() -> None:
    md = MD_PATH.read_text(encoding="utf-8")
    body = md_to_html(md)
    html = TEMPLATE.format(css=CSS, body=body)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {HTML_PATH}")


if __name__ == "__main__":
    main()
