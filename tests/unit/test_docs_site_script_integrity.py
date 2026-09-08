"""Contract: third-party scripts in the docs build are pinned and hashed (FB-16).

The MkDocs site is not published: `mkdocs build --strict` is a CI check and
`mkdocs serve` is a local preview, and GitHub Pages serves the self-contained
`site/` landing page instead. So the Mermaid script unpkg served through
`extra_javascript` -- a bare `<script src>` with no Subresource Integrity --
ran in maintainers' browsers rather than readers'. The tag moved to
`overrides/main.html`, which can carry the attributes; these tests keep it
there, and keep `extra_javascript` from becoming the back door again the day
the docs are published.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MKDOCS_CONFIG = PROJECT_ROOT / "mkdocs.yml"
OVERRIDES_DIR = PROJECT_ROOT / "overrides"
MAIN_TEMPLATE = OVERRIDES_DIR / "main.html"

SCRIPT_TAG = re.compile(r"<script\b[^>]*>", re.IGNORECASE | re.DOTALL)
SRC_ATTR = re.compile(r'\bsrc\s*=\s*"([^"]+)"', re.IGNORECASE)
INTEGRITY_ATTR = re.compile(r'\bintegrity\s*=\s*"(sha(?:256|384|512)-[A-Za-z0-9+/=]{40,})"')
EXACT_VERSION = re.compile(r"@\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?/")

# Keys whose values MkDocs renders as plain tags with no integrity support.
UNHASHABLE_CONFIG_KEYS = ("extra_javascript", "extra_css")


def _config_text() -> str:
    return MKDOCS_CONFIG.read_text(encoding="utf-8")


def _block_values(text: str, key: str) -> list[str]:
    """Return the list entries under a top-level `key:` in mkdocs.yml."""

    values: list[str] = []
    collecting = False
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            collecting = True
            continue
        if collecting:
            if line.strip() and not line.startswith((" ", "\t", "-")):
                break
            if line.strip().startswith("- "):
                values.append(line.strip()[2:].strip())
    return values


def _external_scripts(template: Path) -> list[str]:
    text = template.read_text(encoding="utf-8")
    tags = []
    for tag in SCRIPT_TAG.findall(text):
        src = SRC_ATTR.search(tag)
        if src and src.group(1).lower().startswith(("http://", "https://", "//")):
            tags.append(tag)
    return tags


def test_theme_renders_through_the_overrides_directory() -> None:
    text = _config_text()
    assert "custom_dir: overrides" in text, (
        "the theme must render through overrides/, or main.html is never used and the "
        "Mermaid tag silently disappears from the site"
    )
    assert MAIN_TEMPLATE.is_file()
    assert "{% extends " in MAIN_TEMPLATE.read_text(encoding="utf-8")


def test_mkdocs_config_loads_no_remote_asset_it_cannot_hash() -> None:
    text = _config_text()
    for key in UNHASHABLE_CONFIG_KEYS:
        for value in _block_values(text, key):
            assert not value.lower().startswith(("http://", "https://", "//")), (
                f"{key} entry {value!r} is rendered as a bare tag with no integrity "
                "attribute; put remote assets in overrides/main.html instead"
            )


def test_every_remote_script_in_the_theme_is_version_pinned_and_hashed() -> None:
    templates = sorted(OVERRIDES_DIR.glob("*.html"))
    assert templates, "overrides/ must contain at least the main template"

    for template in templates:
        for tag in _external_scripts(template):
            src = SRC_ATTR.search(tag).group(1)
            assert EXACT_VERSION.search(src), (
                f"{template.name}: {src} does not pin an exact version, so its hash "
                "cannot stay true"
            )
            assert INTEGRITY_ATTR.search(tag), (
                f"{template.name}: {src} has no Subresource Integrity hash"
            )
            assert "crossorigin" in tag.lower(), (
                f"{template.name}: {src} needs crossorigin, or the browser skips the "
                "integrity check on a cross-origin response entirely"
            )


def test_mermaid_fences_stay_on_the_div_format_the_pinned_script_renders() -> None:
    text = _config_text()
    assert "fence_div_format" in text
    assert "fence_code_format" not in text, (
        "fence_code_format emits <pre class='mermaid'>, which hands rendering to the "
        "Material bundle; its own loader falls back to an unpinned "
        "https://unpkg.com/mermaid@11/dist/mermaid.min.js with no integrity"
    )
