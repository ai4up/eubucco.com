#!/usr/bin/env python3
"""Render a Jupyter notebook into a clean, theme-adaptive HTML fragment for the EUBUCCO site.

This is a purpose-built renderer (not nbconvert/pretty-jupyter) that produces a fragment which
extends the site's DaisyUI design: it adapts to both the `pastel` (light) and `night` (dark)
themes from a single file, extracts heavy assets (plot PNGs, the Folium map) to static files so
the committed template stays small, and degrades gracefully on outputs that can't render
statically (Jupyter widgets such as the Lonboard GPU map, tqdm progress bars).

There is a SINGLE source of truth: eubucco/static/notebooks/getting-started.ipynb. That same
file is what users download AND what this script reads to render the page, so the page always
matches the download. Edit that notebook, then re-run this script.

Usage:
    python scripts/render_tutorial_notebook.py            # uses the in-repo notebook
    python scripts/render_tutorial_notebook.py OTHER.ipynb  # override the source

Outputs (paths are repo-relative, hardcoded for the getting-started tutorial):
    eubucco/templates/tutorials/_getting_started_notebook.html   (Django include fragment)
    eubucco/static/notebooks/getting-started/*.png|*.html         (extracted assets)
"""
from __future__ import annotations

import base64
import html
import json
import re
import sys
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

REPO = Path(__file__).resolve().parent.parent
# Single source of truth: the notebook users download is also what we render.
NOTEBOOK = REPO / "eubucco/static/notebooks/getting-started.ipynb"
FRAGMENT_OUT = REPO / "eubucco/templates/tutorials/_getting_started_notebook.html"
ASSET_DIR = REPO / "eubucco/static/notebooks/getting-started"
ASSET_URL = "/static/notebooks/getting-started"

_lexer = PythonLexer()
_formatter = HtmlFormatter(cssclass="hl", nowrap=False)


# --------------------------------------------------------------------------------------
# Minimal markdown -> HTML (the notebook only uses headings, inline code, bold, links, p)
# --------------------------------------------------------------------------------------
def _inline_md(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )
    return text


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def render_markdown(src: str, sections: list) -> str:
    """Return HTML for a markdown cell, recording H2 sections for the TOC."""
    out = []
    para: list[str] = []

    def flush():
        if para:
            out.append(f"<p>{_inline_md(' '.join(para))}</p>")
            para.clear()

    for raw in src.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if line.startswith("### "):
            flush()
            title = line[4:].strip()
            out.append(f'<h3 class="nb-h3">{_inline_md(title)}</h3>')
        elif line.startswith("## "):
            flush()
            title = line[3:].strip()
            sid = slugify(title)
            sections.append((sid, title))
            out.append(f'<h2 id="{sid}" class="nb-h2">{_inline_md(title)}</h2>')
        elif line.startswith("# "):
            flush()
            out.append(f'<h2 class="nb-h2">{_inline_md(line[2:].strip())}</h2>')
        else:
            para.append(line.strip())
    flush()
    return "\n".join(out)


# --------------------------------------------------------------------------------------
# Code + outputs
# --------------------------------------------------------------------------------------
def render_code(src: str) -> str:
    code_html = highlight(src.strip("\n"), _lexer, _formatter)
    return (
        '<div class="nb-code" data-code="in">'
        '  <div class="nb-code-bar">'
        '    <span class="nb-dot"></span><span class="nb-lang">python</span>'
        '    <button class="nb-copy" type="button" aria-label="Copy code">Copy</button>'
        "  </div>"
        f"  {code_html}"
        "</div>"
    )


_REPR_RE = re.compile(r"^<[\w.]+ (object )?at 0x[0-9a-f]+>$")
# Matplotlib artist reprs that leak in as execute_result text alongside a figure.
_MPL_PREFIXES = ("Text(", "<Axes", "<Figure", "[<matplotlib", "<matplotlib", "(<Figure")


def _is_trivial_repr(text: str) -> bool:
    t = text.strip()
    return (
        bool(_REPR_RE.match(t))
        or t.startswith("<_duckdb.")
        or t.startswith(_MPL_PREFIXES)
    )


def clean_dataframe_html(raw: str) -> str:
    # Drop pandas' scoped <style> block; we restyle .dataframe ourselves.
    raw = re.sub(r"<style scoped>.*?</style>", "", raw, flags=re.DOTALL)
    return raw.strip()


def _clean_stream(text: str) -> str | None:
    # Collapse carriage-return progress output to its final frame.
    text = text.split("\r")[-1]
    stripped = text.strip()
    if not stripped:
        return None
    # Drop noisy library warnings and progress bars (curl/tqdm/aws).
    low = stripped.lower()
    if "warn" in low or "site-packages" in stripped:
        return None
    if stripped.count("#") > len(stripped) * 0.3 or stripped.count("█") > 3:
        return None
    return text.rstrip()


def render_outputs(outputs: list, idx: int, assets: dict, is_lonboard: bool = False) -> str:
    blocks: list[str] = []
    for out in outputs:
        otype = out.get("output_type")
        data = out.get("data", {})

        if otype == "stream":
            cleaned = _clean_stream("".join(out.get("text", [])))
            if cleaned:
                blocks.append(f'<pre class="nb-stream">{html.escape(cleaned)}</pre>')
            continue

        # Prefer richest representation.
        if "text/html" in data:
            df_html = clean_dataframe_html("".join(data["text/html"]))
            blocks.append(f'<div class="nb-table">{df_html}</div>')
            continue

        if "image/png" in data:
            b64 = data["image/png"]
            if isinstance(b64, list):
                b64 = "".join(b64)
            fname = f"plot-{idx}.png"
            (ASSET_DIR / fname).write_bytes(base64.b64decode(b64))
            assets[fname] = True
            blocks.append(
                f'<figure class="nb-figure"><img loading="lazy" '
                f'src="{ASSET_URL}/{fname}" alt="Plot output from cell {idx}"></figure>'
            )
            continue

        if "application/vnd.jupyter.widget-view+json" in data:
            # Widget state isn't serialized. Only the Lonboard GPU map is worth a
            # placeholder; tqdm/aws progress widgets are transient noise -> drop.
            if is_lonboard:
                blocks.append(render_widget_placeholder(idx))
            continue

        if "text/plain" in data:
            text = "".join(data["text/plain"])
            if _is_trivial_repr(text):
                continue
            blocks.append(f'<pre class="nb-stream">{html.escape(text.rstrip())}</pre>')

    if not blocks:
        return ""
    return '<div class="nb-out"><span class="nb-out-label">Output</span>' + "\n".join(blocks) + "</div>"


def render_widget_placeholder(idx: int) -> str:
    """Lonboard / interactive widgets don't serialize state -> show a tasteful note."""
    return (
        '<div class="nb-widget">'
        '  <div class="nb-widget-icon" aria-hidden="true">'
        '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">'
        '      <path d="M9 3 3 6v15l6-3 6 3 6-3V3l-6 3-6-3Z" stroke-linejoin="round"/>'
        '      <path d="M9 3v15M15 6v15" stroke-linejoin="round"/></svg>'
        "  </div>"
        "  <div>"
        '    <p class="nb-widget-title">Interactive GPU map (Lonboard / deck.gl)</p>'
        '    <p class="nb-widget-sub">This view renders live in the notebook. '
        'Download the notebook below to explore it in 3D yourself.</p>'
        "  </div>"
        "</div>"
    )


def extract_folium(outputs: list) -> str | None:
    """Pull the big Folium map HTML out to a static file; return its filename or None."""
    for out in outputs:
        data = out.get("data", {})
        html_str = "".join(data.get("text/html", []))
        if "folium" in html_str or "leaflet" in html_str.lower():
            fname = "folium-map.html"
            doc = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<style>html,body{margin:0;padding:0;height:100%;background:#fff}</style>"
                f"</head><body>{html_str}</body></html>"
            )
            (ASSET_DIR / fname).write_text(doc, encoding="utf-8")
            return fname
    return None


def is_folium_cell(src: str) -> bool:
    return ".explore(" in src or "folium" in src.lower()


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def main(src_path: str) -> None:
    nb = json.loads(Path(src_path).read_text())
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    # Clear previously generated assets so renaming/removing cells can't leave orphans
    # (assets are keyed by cell index, which shifts when the notebook is edited).
    for stale in [*ASSET_DIR.glob("plot-*.png"), *ASSET_DIR.glob("folium-map.html")]:
        stale.unlink()

    sections: list = []
    body: list[str] = []
    assets: dict = {}

    cells = nb["cells"]
    for idx, cell in enumerate(cells):
        ctype = cell["cell_type"]
        src = "".join(cell["source"])
        if not src.strip():
            continue

        if ctype == "markdown":
            body.append('<div class="nb-md">' + render_markdown(src, sections) + "</div>")

        elif ctype == "code":
            cell_html = ['<div class="nb-cell">', render_code(src)]
            outputs = cell.get("outputs", [])

            if is_folium_cell(src):
                fname = extract_folium(outputs)
                if fname:
                    cell_html.append(
                        '<div class="nb-out"><span class="nb-out-label">Output</span>'
                        '<div class="nb-folium" data-map="' + f"{ASSET_URL}/{fname}" + '">'
                        '  <button class="nb-folium-load" type="button">'
                        '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">'
                        '      <circle cx="12" cy="10" r="3"/>'
                        '      <path d="M12 2a8 8 0 0 0-8 8c0 5.25 8 12 8 12s8-6.75 8-12a8 8 0 0 0-8-8Z" stroke-linejoin="round"/></svg>'
                        "    Load interactive map"
                        "  </button>"
                        "</div></div>"
                    )
            else:
                is_lonboard = "lonboard" in src.lower()
                cell_html.append(render_outputs(outputs, idx, assets, is_lonboard=is_lonboard))

            cell_html.append("</div>")
            body.append("\n".join(p for p in cell_html if p))

    # Table of contents from H2 sections.
    toc_items = "\n".join(
        f'<li><a href="#{sid}">{html.escape(title)}</a></li>' for sid, title in sections
    )

    fragment = (
        "{# AUTO-GENERATED by scripts/render_tutorial_notebook.py — do not edit by hand. #}\n"
        '<div class="nb-layout">\n'
        '  <article class="nb">\n'
        + "\n".join(body)
        + "\n  </article>\n"
        f'  <nav class="nb-toc" aria-label="On this page">\n'
        '    <div class="nb-toc-inner">\n'
        '      <p class="nb-toc-title">On this page</p>\n'
        f"      <ul>\n{toc_items}\n      </ul>\n"
        "    </div>\n"
        "  </nav>\n"
        "</div>\n"
    )

    FRAGMENT_OUT.write_text(fragment, encoding="utf-8")

    src_disp = Path(src_path)
    src_disp = src_disp.relative_to(REPO) if src_disp.resolve().is_relative_to(REPO) else src_disp
    print(f"source     -> {src_disp} (also the download)")
    print(f"fragment   -> {FRAGMENT_OUT.relative_to(REPO)}  ({FRAGMENT_OUT.stat().st_size//1024} KB)")
    print(f"sections   -> {[t for _, t in sections]}")
    print(f"assets     -> {sorted(p.name for p in ASSET_DIR.iterdir())}")


if __name__ == "__main__":
    if len(sys.argv) > 2:
        sys.exit("usage: python scripts/render_tutorial_notebook.py [SOURCE.ipynb]")
    main(sys.argv[1] if len(sys.argv) == 2 else str(NOTEBOOK))
