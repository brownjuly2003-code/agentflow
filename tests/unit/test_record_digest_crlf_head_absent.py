"""Regression: CRLF evidence records without a HEAD blob hash LF-folded bytes."""

from __future__ import annotations

import hashlib

from tests.unit import test_docs_evidence_index as evidence_index


def test_record_digest_crlf_without_head_blob_hashes_lf_folded_bytes(tmp_path, monkeypatch) -> None:
    relative = "docs/perf/unpublished-crlf-record.md"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    working_lf = b"# unpublished CRLF record\nbody\n"
    target.write_bytes(working_lf.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(evidence_index, "ROOT", tmp_path)

    digest = evidence_index._record_digest(relative)

    assert digest == hashlib.sha256(working_lf).hexdigest()
