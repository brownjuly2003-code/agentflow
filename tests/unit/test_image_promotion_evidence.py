import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from scripts.write_image_promotion_evidence import build_promotion_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_REF = "ghcr.io/example/agentflow-api"
IMAGE_DIGEST = "sha256:" + "d" * 64
SOURCE_SHA = "c" * 40


def test_promotion_evidence_renders_the_exact_built_digest(tmp_path: Path) -> None:
    helm = shutil.which("helm")
    assert helm is not None

    packet = build_promotion_evidence(
        image_ref=IMAGE_REF,
        image_digest=IMAGE_DIGEST,
        source_sha=SOURCE_SHA,
        run_id="123456",
        chart_path=PROJECT_ROOT / "helm" / "agentflow",
        output_dir=tmp_path,
        helm_executable=helm,
    )

    subject = f"{IMAGE_REF}@{IMAGE_DIGEST}"
    values = yaml.safe_load((tmp_path / "image-values.yaml").read_text(encoding="utf-8"))
    manifest = (tmp_path / "helm-deployment.yaml").read_text(encoding="utf-8")
    persisted = json.loads((tmp_path / "promotion.json").read_text(encoding="utf-8"))

    assert values["image"] == {"repository": IMAGE_REF, "digest": IMAGE_DIGEST}
    assert f'image: "{subject}"' in manifest
    assert f"{IMAGE_REF}:2.0.0" not in manifest
    assert packet == persisted
    assert packet["image"] == {
        "repository": IMAGE_REF,
        "digest": IMAGE_DIGEST,
        "subject": subject,
    }
    assert packet["source"] == {"git_sha": SOURCE_SHA}
    assert packet["build"] == {
        "workflow": "container-attestation",
        "run_id": "123456",
    }
    assert packet["helm"]["manifest_sha256"] == hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    assert packet["scope"]["proves"] == [
        "the Helm API deployment references the workflow-built image digest"
    ]
    assert "staging rollout" in packet["scope"]["does_not_prove"]
    assert "production acceptance" in packet["scope"]["does_not_prove"]


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"image_digest": "sha256:ABC"}, "image_digest"),
        ({"image_ref": "ghcr.io/example/agentflow-api:latest"}, "image_ref"),
        ({"image_ref": f"{IMAGE_REF}@{IMAGE_DIGEST}"}, "image_ref"),
        ({"source_sha": "not-a-git-sha"}, "source_sha"),
        ({"run_id": "run-123"}, "run_id"),
    ],
)
def test_promotion_evidence_rejects_unverifiable_identity(
    tmp_path: Path,
    patch: dict[str, str],
    message: str,
) -> None:
    arguments = {
        "image_ref": IMAGE_REF,
        "image_digest": IMAGE_DIGEST,
        "source_sha": SOURCE_SHA,
        "run_id": "123456",
        "chart_path": PROJECT_ROOT / "helm" / "agentflow",
        "output_dir": tmp_path,
        "helm_executable": "helm",
    }
    arguments.update(patch)

    with pytest.raises(ValueError, match=message):
        build_promotion_evidence(**arguments)

    assert not tmp_path.exists() or not any(tmp_path.iterdir())
