"""Tolerant parsing of the SQL-JSON envelope a browser-routed model emits.

Vendored from the NL_SQL portfolio engine
(``nl_sql.llm.providers.perplexity``) as part of AgentFlow ADR 0008. The
GraceKelly browser path returns the ``{"sql": "...", "rationale": ...}``
output-contract envelope (sometimes with terminal ANSI colour codes the
Markdown layer leaves behind, sometimes with literal newlines inside the SQL
value that break strict ``json.loads``). These helpers strip the ANSI noise
and unwrap the envelope down to the bare SELECT.
"""

from __future__ import annotations

import json
import re

# Terminal colour codes the Perplexity/GraceKelly Markdown pipeline can leave
# behind in the answer text.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\[[0-9;]+m")

# Envelope-shape sniff: does the text start with a JSON object carrying a
# "sql" key? Cheap gate before we attempt any parsing.
_SQL_JSON_HINT = re.compile(r'^\s*\{.*"sql"\s*:', re.DOTALL)

# Structural extraction of the "sql" value used when strict json.loads fails
# because the SQL value contains literal newlines.
_SQL_KV_RE = re.compile(r'"sql"\s*:\s*"((?:\\.|[^"\\])*)"')

_JSON_ESCAPE_RE = re.compile(r"\\(.)")
_JSON_ESCAPE_TABLE = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _decode_json_string_escapes(raw: str) -> str:
    """Decode JSON string escapes left-to-right in a single pass.

    Unknown escapes (e.g. ``\\u`` Unicode sequences) pass through unchanged —
    the real browser payloads don't use them, and handling them properly would
    require pulling a real JSON parser back in (defeating the point of this
    tolerant fallback).
    """
    return _JSON_ESCAPE_RE.sub(
        lambda m: _JSON_ESCAPE_TABLE.get(m.group(1), m.group(0)),
        raw,
    )


def unwrap_sql_json(text: str) -> str:
    """If ``text`` is the JSON output-contract envelope, return just the SQL."""
    if not _SQL_JSON_HINT.match(text):
        return text
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Tolerate trailing prose after the JSON object by snipping at the
        # final balanced brace and retrying.
        last = text.rfind("}")
        obj = None
        if last != -1:
            try:
                obj = json.loads(text[: last + 1])
            except json.JSONDecodeError:
                obj = None
    if isinstance(obj, dict):
        sql = obj.get("sql")
        if isinstance(sql, str) and sql.strip():
            return sql.strip()
    # Regex fallback: strict JSON parsing fails when the SQL value contains
    # literal newlines (which the browser Markdown layer routinely inserts).
    # Pull the SQL value out by structure. Safe because the envelope shape is
    # already confirmed by `_SQL_JSON_HINT.match` above.
    match = _SQL_KV_RE.search(text)
    if match:
        sql = _decode_json_string_escapes(match.group(1)).strip()
        if sql:
            return sql
    return text


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)
