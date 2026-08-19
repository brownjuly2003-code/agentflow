"""Contract tests for scripts/soak/stamp_soak_identity.py.

Uses a small synthetic mirror in tmp_path. Does not read the untracked -06 pack.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "soak" / "stamp_soak_identity.py"

SOURCE_ID = "20260101-01"
NEW_ID = "20260102-02"
OLD_EVENT = "aaaabbbb-cccc-4ddd-8eee-"
NEW_EVENT = "ffffeeee-dddd-4ccc-8bbb-"
OLD_ORDER = "ORD-20260101-0100"
NEW_ORDER = "ORD-20260102-0200"
KEPT_KAFKA = "agentflow-golden-soak-rv-20260802-01"
KEPT_LABEL = "20260802-01"


def _load_module():
    assert SCRIPT_PATH.exists(), f"missing stamper at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("stamp_soak_identity_under_test", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _template(root: Path, *, omit: str | None = None) -> Path:
    files = {
        "_flink_recover.sh": """#!/usr/bin/env bash
# recover 20260101-01; history soak-05 stays; identity -01
log "=== recover Flink for soak -01 ==="
python3 - <<PY
import json
from pathlib import Path
merge = {
  "spec": {
    "flinkConfiguration": {
      "execution.checkpointing.min-pause": "2000 ms",
      "execution.checkpointing.interval": "1000 ms",
    }
  }
}
Path("$OUT/fix-merge.json").write_text(json.dumps(merge, indent=2)+"\\n")
print("merge_written")
PY
set +e
PATCH_OUT=$("$KUBECTL" --context "$CTX" -n "$NS" patch flinkdeployment "$CR" --type=merge --patch-file "$OUT/fix-merge.json" 2>&1)
RC=$?
set -e
echo "$PATCH_OUT" | tee "$OUT/fix-patch-out.txt"
[[ $RC -eq 0 ]] || fail "patch_failed rc=$RC"
"$KUBECTL" --context "$CTX" -n "$NS" get flinkdeployment "$CR" -o json > "$OUT/flink-cr-final.json"
python3 - <<PY
import json
from pathlib import Path
out=Path("$OUT")
cr=json.load(open(out/"flink-cr-final.json"))
fc=cr["spec"]["flinkConfiguration"]
assert fc.get("restart-strategy.type")=="failure-rate", fc.get("restart-strategy.type")
doc={
  "result": "FLINK_RECOVER_01_PASS",
  "not_done": ["watcher_arm", "soak-01 traffic", "verify"],
}
(out/"result.json").write_text(json.dumps(doc, indent=2)+"\\n")
(out/"result.txt").write_text("RESULT=FLINK_RECOVER_01_PASS\\n")
print(json.dumps(doc, indent=2))
PY
""",
        "_remote_soak_start.sh": """#!/usr/bin/env bash
set -euo pipefail
PACK_REMOTE=/tmp/soak-pack-20260101-01
OUT=/tmp/agentflow-soak-runtime-20260101-01
RUN_LABEL=golden-4h-soak-rv-20260101-01
EVENT_PREFIX=aaaabbbb-cccc-4ddd-8eee-
ORDER_PREFIX=ORD-20260101-0100
FLINK_GROUP=agentflow-golden-soak-rv-20260802-01
VERIFY_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
PRODUCER_SHA=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
# Sequence: preflight → Gate A → baseline → observer → producer.
# history soak-05 must remain
if ! "$KUBECTL" --context "$CTX" -n "$NS" wait --for=condition=complete "job/$BASELINE_JOB" --timeout=600s; then
  "$KUBECTL" --context "$CTX" -n "$NS" logs "job/$BASELINE_JOB" --tail=80 > "$OUT/logs-baseline.txt" || true
  fail "baseline_not_complete"
fi
log "baseline PASS"
""",
        "_remote_soak_watchdog.sh": """#!/usr/bin/env bash
# watchdog 20260101-01 soak-05 history
OUT=/tmp/agentflow-soak-runtime-20260101-01
FLINK_GROUP=agentflow-golden-soak-rv-20260802-01
""",
        "_watcher_start.sh": """#!/usr/bin/env bash
# watcher 20260101-01 identity -01
fail(){ log "FAIL_CLOSED: $*"; echo "RESULT=FAIL reason=$*"; exit 1; }
if pgrep -f "capture_flink_failure_evidence.py watch" >/dev/null 2>&1; then
  fail "watcher_already_running"
fi
nohup python3 "$W/capture_flink_failure_evidence.py" watch \\
  --timeout-seconds 21600 > "$W/watch.log" 2>&1 &
WPID=$!
if ! kill -0 "$WPID" 2>/dev/null; then
  fail "watcher_exited_early"
fi
fail "watcher_not_armed_after_180s pid=$WPID"
""",
        "_status.sh": """#!/usr/bin/env bash
export DOCKER_HOST="unix:///Users/julia/.colima/agentflow-fc5-7113966/docker.sock"
OUT=/tmp/agentflow-soak-runtime-20260101-01
echo "$OV" | python3 -c 'import json,sys;d=json.load(sys.stdin);js=d.get("jobs") or [];
print("flink=no_jobs" if not js else "x")'
""",
        "pack/baseline.py": (
            "SOURCE = 'golden-4h-soak-rv-20260101-01'\n"
            "EVENT_PREFIX = 'aaaabbbb-cccc-4ddd-8eee-'\n"
            "ORDER_PREFIX = 'ORD-20260101-0100'\n"
        ),
        "pack/observer.py": (
            'run_label = "golden-4h-soak-rv-20260802-01"\n# pack identity 20260101-01\n'
        ),
        "pack/producer.py": 'print("producer-20260101-01")\n',
        "pack/verify.py": (f'print("verify-20260101-01")\nflink_group = "{KEPT_KAFKA}"\n'),
        "pack/baseline-job.yaml": "name: agentflow-golden-4h-baseline-20260101-01\n",
        "pack/soak-observer-job.yaml": "name: agentflow-golden-4h-observer-20260101-01\n",
        "pack/soak-producer-job.yaml": (
            "name: agentflow-golden-4h-producer-20260101-01\n"
            f"EVENT_PREFIX: {OLD_EVENT}\n"
            f"ORDER_PREFIX: {OLD_ORDER}\n"
        ),
        "pack/soak-verify-job.yaml": (
            f"name: agentflow-golden-4h-verify-20260101-01\nFLINK_SOURCE_GROUP: {KEPT_KAFKA}\n"
        ),
    }
    source = root / "source"
    for relative, text in files.items():
        if omit is not None and relative == omit:
            continue
        _write(source / relative, text)
    return source


def _stamp_args(
    module,
    source: Path,
    out: Path,
    watcher: Path,
    *,
    force: bool = False,
    ha: tuple[int, int, int] | None = None,
) -> list[str]:
    args = [
        "--source-dir",
        str(source),
        "--source-identity",
        SOURCE_ID,
        "--identity",
        NEW_ID,
        "--event-prefix",
        NEW_EVENT,
        "--order-prefix",
        NEW_ORDER,
        "--out-dir",
        str(out),
        "--watcher-script",
        str(watcher),
        "--checkpoint-interval-ms",
        "10000",
        "--checkpoint-min-pause-ms",
        "10000",
        "--watcher-poll-seconds",
        "30",
        "--watcher-grace-seconds",
        "90",
    ]
    if ha is not None:
        args.extend(
            [
                "--ha-lease-duration-seconds",
                str(ha[0]),
                "--ha-renew-deadline-seconds",
                str(ha[1]),
                "--ha-retry-period-seconds",
                str(ha[2]),
            ]
        )
    if force:
        args.append("--force")
    return args


def _write_watcher(root: Path) -> Path:
    path = root / "fake_watcher.py"
    _write(path, "print('fake-watcher')\n")
    return path


def test_substitution_completeness(tmp_path: Path) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    rc = module.main(_stamp_args(module, source, out, _write_watcher(tmp_path)))
    assert rc == 0

    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["unresolved"] == []
    assert manifest["identity"] == NEW_ID
    assert manifest["source_identity"] == SOURCE_ID
    assert manifest["event_prefix"] == NEW_EVENT
    assert manifest["order_prefix"] == NEW_ORDER

    text_files = [
        path
        for path in out.rglob("*")
        if path.is_file()
        and path.suffix in {".sh", ".py", ".yaml", ".yml", ".md", ".json", ".txt"}
        and path.name not in {"MANIFEST.json", "DIFF_VS_SOURCE.md", "LAUNCH_ORDER.md"}
    ]
    for path in text_files:
        body = path.read_text(encoding="utf-8")
        assert SOURCE_ID not in body, path
        assert (
            KEPT_KAFKA in body
            or KEPT_LABEL in body
            or path.name
            not in {
                "observer.py",
                "verify.py",
                "_remote_soak_start.sh",
                "_remote_soak_watchdog.sh",
                "soak-verify-job.yaml",
            }
        )

    start = (out / "_remote_soak_start.sh").read_text(encoding="utf-8")
    assert f"EVENT_PREFIX={NEW_EVENT}" in start
    assert f"ORDER_PREFIX={NEW_ORDER}" in start
    assert SOURCE_ID not in start
    assert NEW_ID in start
    assert KEPT_KAFKA in start
    assert "soak-05" in start

    observer = (out / "pack/observer.py").read_text(encoding="utf-8")
    assert f"golden-4h-soak-rv-{KEPT_LABEL}" in observer
    assert SOURCE_ID not in observer

    verify = (out / "pack/verify.py").read_text(encoding="utf-8")
    assert KEPT_KAFKA in verify


def test_sha_pins_match_stamped_pack_files(tmp_path: Path) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    assert module.main(_stamp_args(module, source, out, _write_watcher(tmp_path))) == 0

    start = (out / "_remote_soak_start.sh").read_text(encoding="utf-8")
    verify_line = next(line for line in start.splitlines() if line.startswith("VERIFY_SHA="))
    producer_line = next(line for line in start.splitlines() if line.startswith("PRODUCER_SHA="))
    assert verify_line == f"VERIFY_SHA={_sha(out / 'pack' / 'verify.py')}"
    assert producer_line == f"PRODUCER_SHA={_sha(out / 'pack' / 'producer.py')}"


def test_robustness_rewrites(tmp_path: Path) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    assert module.main(_stamp_args(module, source, out, _write_watcher(tmp_path))) == 0

    start = (out / "_remote_soak_start.sh").read_text(encoding="utf-8")
    assert "wait --for=condition=complete" not in start
    assert ".status.succeeded" in start
    assert ".status.failed" in start
    assert "sleep 15" in start
    assert 'log "baseline PASS"' in start
    pass_at = start.index('log "baseline PASS"')
    watcher_at = start.index("watcher_not_armed")
    observer_at = start.index("baseline → watcher → observer → producer")
    assert pass_at < watcher_at
    assert f"bash /tmp/agentflow-soak-ctl-{NEW_ID}/_watcher_start.sh" in start
    assert observer_at >= 0

    watcher = (out / "_watcher_start.sh").read_text(encoding="utf-8")
    assert "--poll-interval-seconds 30" in watcher
    assert "--transitional-grace-seconds 90" in watcher
    pgrep_line = next(line for line in watcher.splitlines() if "pgrep" in line)
    invoke_line = next(
        line for line in watcher.splitlines() if "python3" in line and "watch" in line
    )
    assert "--poll-interval-seconds" not in pgrep_line
    assert "--poll-interval-seconds 30" in invoke_line
    assert "--transitional-grace-seconds 90" in invoke_line
    assert 'kill "$WPID"' in watcher
    assert "stop_own_watcher" in watcher

    recover = (out / "_flink_recover.sh").read_text(encoding="utf-8")
    assert '"execution.checkpointing.interval": "10000 ms"' in recover
    assert '"execution.checkpointing.min-pause": "10000 ms"' in recover
    assert "1000 ms" not in recover
    assert "2000 ms" not in recover
    assert module.ENV_REWRITE_MARKER in recover
    assert "FLINK_CHECKPOINT_INTERVAL_MS" in recover
    assert "FLINK_CHECKPOINT_MIN_PAUSE_MS" in recover
    assert "containers" in recover
    assert "resourceVersion" in recover
    assert 'fail "patch_conflict"' in recover
    assert "RESULT=FLINK_RECOVER_02_PASS" in recover
    assert '"result": "FLINK_RECOVER_02_PASS"' in recover
    assert "FLINK_RECOVER_01_PASS" not in recover

    status = (out / "_status.sh").read_text(encoding="utf-8")
    assert "python3 -c" not in status
    assert "python3 - <<'PY'" in status
    assert "export DOCKER_HOST=" in status
    assert "jobs-overview-status.json" in status


def test_idempotent_and_refuses_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    watcher = _write_watcher(tmp_path)
    assert module.main(_stamp_args(module, source, out, watcher)) == 0
    first = {
        path.relative_to(out).as_posix(): path.read_bytes()
        for path in out.rglob("*")
        if path.is_file()
    }

    refused = module.main(_stamp_args(module, source, out, watcher))
    assert refused == 1
    err = capsys.readouterr().err
    assert "refusing to overwrite" in err

    assert module.main(_stamp_args(module, source, out, watcher, force=True)) == 0
    second = {
        path.relative_to(out).as_posix(): path.read_bytes()
        for path in out.rglob("*")
        if path.is_file()
    }
    assert first == second


def test_refuses_missing_required_source_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    source = _template(tmp_path, omit="_status.sh")
    out = tmp_path / "out"
    rc = module.main(_stamp_args(module, source, out, _write_watcher(tmp_path)))
    assert rc == 1
    err = capsys.readouterr().err
    assert "missing required source files" in err
    assert "_status.sh" in err
    assert not out.exists()


def test_short_identity_markers_are_stamped(tmp_path: Path) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    assert module.main(_stamp_args(module, source, out, _write_watcher(tmp_path))) == 0

    recover = (out / "_flink_recover.sh").read_text(encoding="utf-8")
    watcher = (out / "_watcher_start.sh").read_text(encoding="utf-8")
    launch = (out / "LAUNCH_ORDER.md").read_text(encoding="utf-8")
    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))

    assert "RESULT=FLINK_RECOVER_02_PASS" in recover
    assert '"result": "FLINK_RECOVER_02_PASS"' in recover
    assert "for soak -02" in recover
    assert "identity -02" in recover
    assert "soak-02 traffic" in recover
    assert "identity -02" in watcher
    assert "FLINK_RECOVER_02_PASS" in launch
    assert "RECOVER_01" not in recover
    assert "soak -01" not in recover
    assert "soak-01" not in recover
    assert "identity -01" not in recover
    assert "identity -01" not in watcher
    assert "soak-05" in recover
    locations = manifest["short_marker_locations"]
    assert locations
    files = {entry["file"] for entry in locations}
    assert "_flink_recover.sh" in files
    assert "_watcher_start.sh" in files
    patterns = {entry["pattern"] for entry in locations}
    assert "RECOVER_01_PASS" in patterns
    assert "identity -01" in patterns
    leftover = module.leftover_short_markers(recover, "01")
    assert leftover == []


def test_leftover_short_markers_are_detected() -> None:
    module = _load_module()
    text = "RESULT=FLINK_RECOVER_01_PASS soak -01 soak-01 identity -01"
    assert module.leftover_short_markers(text, "01") == [
        "RECOVER_01",
        "soak -01",
        "soak-01",
        "identity -01",
    ]


def test_refuses_out_dir_same_as_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_module()
    source = _template(tmp_path)
    recover_before = (source / "_flink_recover.sh").read_bytes()
    rc = module.main(_stamp_args(module, source, source, _write_watcher(tmp_path), force=True))
    assert rc == 1
    err = capsys.readouterr().err
    assert "source-dir" in err
    assert (source / "_flink_recover.sh").read_bytes() == recover_before


def test_refuses_out_dir_descendant_of_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = source / "nested-out"
    rc = module.main(_stamp_args(module, source, out, _write_watcher(tmp_path)))
    assert rc == 1
    err = capsys.readouterr().err
    assert "descendant" in err
    assert not out.exists()
    assert (source / "_flink_recover.sh").is_file()


def test_refuses_out_dir_ancestor_of_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path
    rc = module.main(_stamp_args(module, source, out, _write_watcher(tmp_path), force=True))
    assert rc == 1
    err = capsys.readouterr().err
    assert "ancestor" in err
    assert (source / "_flink_recover.sh").is_file()


def test_failed_validation_keeps_old_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    watcher = _write_watcher(tmp_path)
    assert module.main(_stamp_args(module, source, out, watcher)) == 0
    first = (out / "_flink_recover.sh").read_bytes()
    start = source / "_remote_soak_start.sh"
    start.write_text(
        start.read_text(encoding="utf-8").replace("VERIFY_SHA=", "VERIFY_HASH="),
        encoding="utf-8",
        newline="\n",
    )
    rc = module.main(_stamp_args(module, source, out, watcher, force=True))
    assert rc == 1
    err = capsys.readouterr().err
    assert "VERIFY_SHA" in err
    assert (out / "_flink_recover.sh").read_bytes() == first
    assert not list(tmp_path.glob("out.stamp-tmp-*"))


def test_missing_transform_anchor_does_not_create_out_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_module()
    source = _template(tmp_path)
    start = source / "_remote_soak_start.sh"
    start.write_text(
        start.read_text(encoding="utf-8").replace('log "baseline PASS"\n', ""),
        encoding="utf-8",
        newline="\n",
    )
    out = tmp_path / "out"
    rc = module.main(_stamp_args(module, source, out, _write_watcher(tmp_path)))
    assert rc == 1
    err = capsys.readouterr().err
    assert "watcher_arm" in err
    assert "baseline PASS" in err
    assert not out.exists()


def test_merge_includes_resource_version_and_patch_conflict(tmp_path: Path) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    assert module.main(_stamp_args(module, source, out, _write_watcher(tmp_path))) == 0
    recover = (out / "_flink_recover.sh").read_text(encoding="utf-8")
    assert 'merge.setdefault("metadata", {})["resourceVersion"] = rv' in recover
    assert 'fail "patch_conflict"' in recover
    assert "live_cr_resource_version_missing" in recover


def test_watcher_start_kills_own_pid_on_arm_timeout(tmp_path: Path) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    assert module.main(_stamp_args(module, source, out, _write_watcher(tmp_path))) == 0
    watcher = (out / "_watcher_start.sh").read_text(encoding="utf-8")
    assert 'kill "$WPID"' in watcher
    assert 'stop_own_watcher; fail "watcher_exited_early"' in watcher
    assert 'stop_own_watcher; fail "watcher_not_armed_after_180s pid=$WPID"' in watcher


def test_ha_lease_knobs_injected(tmp_path: Path) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    rc = module.main(_stamp_args(module, source, out, _write_watcher(tmp_path), ha=(60, 45, 5)))
    assert rc == 0
    recover = (out / "_flink_recover.sh").read_text(encoding="utf-8")
    launch = (out / "LAUNCH_ORDER.md").read_text(encoding="utf-8")
    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    assert '"high-availability.kubernetes.leader-election.lease-duration": "60 s"' in recover
    assert '"high-availability.kubernetes.leader-election.renew-deadline": "45 s"' in recover
    assert '"high-availability.kubernetes.leader-election.retry-period": "5 s"' in recover
    assert "high-availability.type" not in recover
    assert "heartbeat" not in recover
    assert manifest["knobs"]["ha_lease_duration_seconds"] == 60
    assert manifest["knobs"]["ha_renew_deadline_seconds"] == 45
    assert manifest["knobs"]["ha_retry_period_seconds"] == 5
    assert "60 s" in launch
    assert "45 s" in launch
    assert "5 s" in launch


def test_ha_knob_validation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_module()
    source = _template(tmp_path)
    out = tmp_path / "out"
    rc = module.main(_stamp_args(module, source, out, _write_watcher(tmp_path), ha=(60, 60, 5)))
    assert rc == 1
    err = capsys.readouterr().err
    assert "ha-renew-deadline-seconds" in err
    assert not out.exists()
