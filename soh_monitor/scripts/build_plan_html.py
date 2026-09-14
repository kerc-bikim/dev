"""Convert plan.md to plan.html."""
from __future__ import annotations

from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

ROOT = Path(__file__).resolve().parents[1]
MD_PATH = ROOT / "plan.md"
HTML_PATH = ROOT / "plan.html"

CSS = """
:root {
  --bg: #f4f6f8;
  --surface: #ffffff;
  --ink: #17212b;
  --muted: #566270;
  --line: #d3dae1;
  --accent: #0d5c63;
  --accent-soft: #dceceb;
  --code-bg: #eef2f4;
  --table-head: #e6eef0;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: "Pretendard", "Noto Sans KR", "Segoe UI", sans-serif;
  color: var(--ink);
  background:
    radial-gradient(1200px 600px at 10% -10%, #e2eeef 0%, transparent 55%),
    radial-gradient(900px 500px at 100% 0%, #e8eef4 0%, transparent 50%),
    var(--bg);
  line-height: 1.65;
}
.wrap {
  max-width: 1000px;
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
  font-size: 0.9rem;
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
  background: #17212b;
  color: #e6eef2;
  padding: 1rem 1.1rem;
  border-radius: 10px;
  overflow-x: auto;
}
pre code { background: transparent; color: inherit; padding: 0; }
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
  <title>관측소 SOH 통합 모니터링 — 계획서</title>
  <style>{css}</style>
</head>
<body>
  <div class="wrap">
    <header class="doc-header">
      <p class="eyebrow">Recorder SOH · Monitoring Plan</p>
      <h1>관측소 SOH 통합 모니터링 — 계획서</h1>
      <p class="meta">Nanometrics Centaur CTR 1차 · FastAPI + React · InfluxDB + Grafana · 구현 전 확정 계획</p>
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
    # 한글 제목의 링크가 살아 있어야 하므로 ASCII 로 깎지 않는 slugify 를 쓴다.
    return markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
        extension_configs={"toc": {"slugify": slugify_unicode}},
    )


def main() -> None:
    md = MD_PATH.read_text(encoding="utf-8")
    body = md_to_html(md)
    html = TEMPLATE.format(css=CSS, body=body)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {HTML_PATH}")


if __name__ == "__main__":
    main()
