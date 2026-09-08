from __future__ import annotations

_ADMIN_KEYS_MARKER = "/admin/keys/"
_REDACTED_SEGMENT = "<redacted>"


def redact_sensitive_path(path: str) -> str:
    """Replace the path segment immediately after ``admin/keys``.

    A credential must never land in logs or traces. Legacy callers (or any
    client still on the old contract) can put a secret into
    ``DELETE /v1/admin/keys/<plaintext>``. Binding that raw path into
    structured logs or span attributes would persist the secret in
    observability backends. This helper is total and allocation-cheap so it
    can run on every request.
    """
    if not path:
        return path

    prefixed = not path.startswith("/")
    work = f"/{path}" if prefixed else path

    start = 0
    pieces: list[str] = []
    while True:
        found = work.find(_ADMIN_KEYS_MARKER, start)
        if found == -1:
            pieces.append(work[start:])
            break
        after_marker = found + len(_ADMIN_KEYS_MARKER)
        pieces.append(work[start:after_marker])
        if after_marker >= len(work):
            break
        next_slash = work.find("/", after_marker)
        if next_slash == after_marker:
            start = after_marker
            continue
        pieces.append(_REDACTED_SEGMENT)
        if next_slash == -1:
            break
        start = next_slash

    result = "".join(pieces)
    return result[1:] if prefixed else result
