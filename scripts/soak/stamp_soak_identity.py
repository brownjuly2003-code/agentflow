#!/usr/bin/env python3
"""Stamp a new golden-soak identity from an existing runtime mirror.

Deterministic: the same arguments produce byte-identical outputs. Refuses to
overwrite an existing --out-dir unless --force is given.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ENV_REWRITE_MARKER = "STAMP_ENV_REWRITE_BY_NAME"
ENV_POST_ASSERT_MARKER = "STAMP_ENV_POST_ASSERT"
TEXT_SUFFIXES = frozenset({".sh", ".py", ".yaml", ".yml", ".md", ".json", ".txt"})
SKIP_DIR_NAMES = frozenset({"__pycache__"})
SKIP_SUFFIXES = frozenset({".pyc"})
REQUIRED_FILES = (
    "_flink_recover.sh",
    "_remote_soak_start.sh",
    "_remote_soak_watchdog.sh",
    "_watcher_start.sh",
    "_status.sh",
    "pack/baseline.py",
    "pack/observer.py",
    "pack/producer.py",
    "pack/verify.py",
    "pack/baseline-job.yaml",
    "pack/soak-observer-job.yaml",
    "pack/soak-producer-job.yaml",
    "pack/soak-verify-job.yaml",
)
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
DEFAULT_DOCKER_HOST = "unix:///Users/julia/.colima/agentflow-fc5-7113966/docker.sock"
DEFAULT_WATCHER_SCRIPT = "scripts/capture_flink_failure_evidence.py"
CONSUMED_SOURCE_NOTE = "20260818-06"

_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_WAIT_BLOCK_RE = re.compile(
    r'if ! (?P<k>"\$KUBECTL"|kubectl) --context "\$CTX" -n "\$NS" '
    r'wait --for=condition=complete "job/\$BASELINE_JOB" --timeout=600s; then\n'
    r'  (?P=k) --context "\$CTX" -n "\$NS" logs "job/\$BASELINE_JOB" '
    r'--tail=80 > "\$OUT/logs-baseline.txt" \|\| true\n'
    r'  fail "baseline_not_complete"\n'
    r"fi\n"
)
_WAIT_LINE_RE = re.compile(r"^[ \t]*.*wait --for=condition=complete.*$", re.M)
_WATCH_INVOKE_RE = re.compile(
    r'((?:nohup\s+)?python3\s+(?:"\$W/)?capture_flink_failure_evidence\.py"?\s+watch\b)'
)
_STATUS_ONELINER_RE = re.compile(r'echo "\$OV" \| python3 -c \'.*?\'', re.S)
_STATUS_ONELINER_LINE_RE = re.compile(r"^[ \t]*python3 -c .*$", re.M)
_CHECKPOINT_INTERVAL_RE = re.compile(r'("execution\.checkpointing\.interval"\s*:\s*")[^"]*(")')
_CHECKPOINT_PAUSE_RE = re.compile(r'("execution\.checkpointing\.min-pause"\s*:\s*")[^"]*(")')
_VERIFY_SHA_RE = re.compile(r"^VERIFY_SHA=.*$", re.M)
_PRODUCER_SHA_RE = re.compile(r"^PRODUCER_SHA=.*$", re.M)


class StampError(Exception):
    """Fail-closed stamper error with a clear message."""


@dataclass(frozen=True)
class StampConfig:
    source_dir: Path
    out_dir: Path
    source_identity: str
    identity: str
    event_prefix: str
    order_prefix: str
    checkpoint_interval_ms: int
    checkpoint_min_pause_ms: int
    watcher_poll_seconds: int
    watcher_grace_seconds: int
    watcher_script: Path
    force: bool


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def posix(path: Path) -> str:
    return path.as_posix()


def decode_text(data: bytes) -> str:
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def encode_text(text: str) -> bytes:
    if not text.endswith("\n"):
        text = text + "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def is_text_name(name: str) -> bool:
    return Path(name).suffix.lower() in TEXT_SUFFIXES


def find_bash() -> Path | None:
    if GIT_BASH.is_file():
        return GIT_BASH
    which = shutil.which("bash")
    if which:
        return Path(which)
    return None


def parse_assignment(text: str, name: str) -> str:
    for raw in text.splitlines():
        match = _ASSIGNMENT_RE.match(raw)
        if match is None or match.group(1) != name:
            continue
        value = match.group(2).strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        return value
    raise StampError(f"{name} not found in _remote_soak_start.sh")


def locate_replacements(text: str, token: str) -> list[int]:
    if not token:
        return []
    return [index + 1 for index, line in enumerate(text.splitlines()) if token in line]


def replace_token(text: str, old: str, new: str) -> tuple[str, int]:
    if not old or old == new:
        return text, 0
    return text.replace(old, new), text.count(old)


def iter_source_files(source_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        files.append(path)
    files.sort(key=lambda item: posix(item.relative_to(source_dir)).lower())
    return files


def missing_required(source_dir: Path) -> list[str]:
    missing: list[str] = []
    for relative in REQUIRED_FILES:
        if not (source_dir / relative).is_file():
            missing.append(relative)
    return missing


def poll_loop(kubectl_token: str) -> str:
    return (
        f"BASELINE_DONE=0\n"
        f"for _bi in $(seq 1 40); do\n"
        f'  SUCC=$({kubectl_token} --context "$CTX" -n "$NS" get job "$BASELINE_JOB"'
        f" -o jsonpath='{{.status.succeeded}}' 2>/dev/null || echo \"\")\n"
        f'  FAILC=$({kubectl_token} --context "$CTX" -n "$NS" get job "$BASELINE_JOB"'
        f" -o jsonpath='{{.status.failed}}' 2>/dev/null || echo \"\")\n"
        f'  if [[ "${{SUCC:-0}}" == "1" ]]; then\n'
        f"    BASELINE_DONE=1\n"
        f"    break\n"
        f"  fi\n"
        f'  if [[ -n "${{FAILC:-}}" && "${{FAILC}}" != "0" && "${{FAILC}}" != "" ]]; then\n'
        f'    {kubectl_token} --context "$CTX" -n "$NS" logs "job/$BASELINE_JOB"'
        f' --tail=80 > "$OUT/logs-baseline.txt" || true\n'
        f'    fail "baseline_not_complete"\n'
        f"  fi\n"
        f"  sleep 15\n"
        f"done\n"
        f'if [[ "$BASELINE_DONE" != "1" ]]; then\n'
        f'  {kubectl_token} --context "$CTX" -n "$NS" logs "job/$BASELINE_JOB"'
        f' --tail=80 > "$OUT/logs-baseline.txt" || true\n'
        f'  fail "baseline_not_complete"\n'
        f"fi\n"
    )


def watcher_arm_block(identity: str) -> str:
    ctl = f"/tmp/agentflow-soak-ctl-{identity}/_watcher_start.sh"  # noqa: S108
    return (
        f'log "PHASE arm watcher"\n'
        f'if ! bash {ctl} | tee "$OUT/watcher-armed.txt"; then\n'
        f'  fail "watcher_not_armed"\n'
        f"fi\n"
        f'WATCHER_LAST="$(tail -n 1 "$OUT/watcher-armed.txt")"\n'
        f'[[ "$WATCHER_LAST" == RESULT=WATCHER_ARMED* ]] || fail "watcher_not_armed"\n'
    )


def status_heredoc() -> str:
    return (
        'echo "$OV" > "${OUT}/jobs-overview-status.json"\n'
        "  STATUS_OV=\"${OUT}/jobs-overview-status.json\" python3 - <<'PY'\n"
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        'payload = Path(os.environ["STATUS_OV"])\n'
        'data = json.loads(payload.read_text(encoding="utf-8"))\n'
        'jobs = data.get("jobs") or []\n'
        "if not jobs:\n"
        '    print("flink=no_jobs")\n'
        "else:\n"
        "    job = jobs[0]\n"
        '    tasks = job.get("tasks") or {}\n'
        "    print(\n"
        "        f\"flink={job.get('state')} \"\n"
        "        f\"tasks={tasks.get('running')}/{tasks.get('total')} \"\n"
        "        f\"jid={job.get('jid')}\"\n"
        "    )\n"
        "PY"
    )


def env_rewrite_python(interval_ms: int, min_pause_ms: int) -> str:
    return (
        f"# {ENV_REWRITE_MARKER}\n"
        'out = Path("$OUT")\n'
        f'interval_ms = "{interval_ms}"\n'
        f'min_pause_ms = "{min_pause_ms}"\n'
        'cr = json.loads((out / "flink-cr-live.json").read_text(encoding="utf-8"))\n'
        "try:\n"
        '    containers = cr["spec"]["podTemplate"]["spec"]["containers"]\n'
        "except (KeyError, TypeError) as exc:\n"
        '    raise SystemExit(f"podtemplate_containers_missing {exc}") from exc\n'
        "if not isinstance(containers, list):\n"
        '    raise SystemExit("podtemplate_containers_not_list")\n'
        "found_interval = False\n"
        "found_pause = False\n"
        "for container in containers:\n"
        '    for env in container.get("env") or []:\n'
        '        name = env.get("name")\n'
        '        if name == "FLINK_CHECKPOINT_INTERVAL_MS":\n'
        '            env["value"] = interval_ms\n'
        "            found_interval = True\n"
        '        elif name == "FLINK_CHECKPOINT_MIN_PAUSE_MS":\n'
        '            env["value"] = min_pause_ms\n'
        "            found_pause = True\n"
        "if not found_interval or not found_pause:\n"
        "    raise SystemExit(\n"
        '        f"checkpoint_env_missing interval={found_interval} pause={found_pause}"\n'
        "    )\n"
    )


def env_post_assert_python(interval_ms: int, min_pause_ms: int) -> str:
    return (
        f"# {ENV_POST_ASSERT_MARKER}\n"
        f'_want_interval = "{interval_ms}"\n'
        f'_want_pause = "{min_pause_ms}"\n'
        "_seen = {}\n"
        'for _container in cr["spec"]["podTemplate"]["spec"]["containers"]:\n'
        '    for _env in _container.get("env") or []:\n'
        '        _name = _env.get("name")\n'
        "        if _name in (\n"
        '            "FLINK_CHECKPOINT_INTERVAL_MS",\n'
        '            "FLINK_CHECKPOINT_MIN_PAUSE_MS",\n'
        "        ):\n"
        '            _seen[_name] = str(_env.get("value"))\n'
        'if _seen.get("FLINK_CHECKPOINT_INTERVAL_MS") != _want_interval or _seen.get(\n'
        '    "FLINK_CHECKPOINT_MIN_PAUSE_MS"\n'
        ") != _want_pause:\n"
        '    raise SystemExit(f"checkpoint_env_not_applied {_seen}")\n'
        'print("checkpoint_env_ok", _seen)\n'
    )


def _heredoc_span(text: str, needle: str) -> tuple[int, int] | None:
    idx = text.find(needle)
    if idx < 0:
        return None
    start = text.rfind("python3 - <<", 0, idx)
    if start < 0:
        return None
    end = text.find("\nPY\n", idx)
    if end < 0:
        end = text.find("\nPY", idx)
        if end < 0:
            return None
        end += len("\nPY")
    else:
        end += len("\nPY\n")
    return start, end


def transform_recover(text: str, interval_ms: int, min_pause_ms: int) -> str:
    text = _CHECKPOINT_INTERVAL_RE.sub(rf"\g<1>{interval_ms} ms\2", text)
    text = _CHECKPOINT_PAUSE_RE.sub(rf"\g<1>{min_pause_ms} ms\2", text)

    live_get = (
        '"$KUBECTL" --context "$CTX" -n "$NS" get flinkdeployment "$CR" '
        '-o json > "$OUT/flink-cr-live.json" || fail "live_cr_fetch_failed"\n\n'
    )
    span = _heredoc_span(text, "fix-merge.json")
    if span is not None:
        start, end = span
        if "flink-cr-live.json" not in text:
            text = text[:start] + live_get + text[start:]
            start += len(live_get)
            end += len(live_get)
        block = text[start:end]
        if ENV_REWRITE_MARKER not in block:
            injected = False
            for anchor in ("from pathlib import Path\n", "import json\n"):
                if anchor in block:
                    block = block.replace(
                        anchor,
                        anchor + env_rewrite_python(interval_ms, min_pause_ms),
                        1,
                    )
                    injected = True
                    break
            if not injected:
                nl = block.find("\n")
                injected_src = env_rewrite_python(interval_ms, min_pause_ms)
                block = block[: nl + 1] + injected_src + block[nl + 1 :]
        assign = (
            'merge.setdefault("spec", {})["podTemplate"] = {"spec": {"containers": containers}}\n'
        )
        if assign not in block:
            write_idx = block.find('Path("$OUT/fix-merge.json")')
            if write_idx < 0:
                write_idx = block.find('out / "fix-merge.json"')
            if write_idx < 0:
                write_idx = block.find("fix-merge.json")
                if write_idx >= 0:
                    write_idx = block.rfind("\n", 0, write_idx) + 1
            if write_idx >= 0:
                block = block[:write_idx] + assign + block[write_idx:]
        text = text[:start] + block + text[end:]
    elif ENV_REWRITE_MARKER not in text:
        text = (
            text.rstrip()
            + "\n\n# "
            + ENV_REWRITE_MARKER
            + "\n# Rewrite FLINK_CHECKPOINT_INTERVAL_MS / "
            + "FLINK_CHECKPOINT_MIN_PAUSE_MS by name\n"
            + "# inside spec.podTemplate.spec.containers[*].env and include the "
            + "full containers list\n"
            + "# in the merge (JSON merge patch replaces lists whole).\n"
        )

    if "flink-cr-final.json" in text and ENV_POST_ASSERT_MARKER not in text:
        assert_line = (
            'assert fc.get("restart-strategy.type")=="failure-rate", '
            'fc.get("restart-strategy.type")\n'
        )
        payload = env_post_assert_python(interval_ms, min_pause_ms)
        if assert_line in text:
            text = text.replace(assert_line, assert_line + payload, 1)
        else:
            load_line = 'cr=json.load(open(out/"flink-cr-final.json"))\n'
            if load_line in text:
                text = text.replace(load_line, load_line + payload, 1)
    return text


def transform_start(text: str, identity: str) -> str:
    text = text.replace(
        "baseline → observer → producer",
        "baseline → watcher → observer → producer",
    )
    if _WAIT_BLOCK_RE.search(text):
        kubectl_token = _WAIT_BLOCK_RE.search(text).group("k")
        text = _WAIT_BLOCK_RE.sub(poll_loop(kubectl_token), text, count=1)
    elif _WAIT_LINE_RE.search(text):
        line = _WAIT_LINE_RE.search(text).group(0)
        kubectl_token = '"$KUBECTL"' if "$KUBECTL" in line else "kubectl"
        text = _WAIT_LINE_RE.sub(poll_loop(kubectl_token).rstrip("\n"), text, count=1)

    if 'log "baseline PASS"' in text and "watcher_not_armed" not in text:
        text = text.replace(
            'log "baseline PASS"\n',
            'log "baseline PASS"\n' + watcher_arm_block(identity),
            1,
        )
    return text


def transform_watcher_start(text: str, poll_seconds: int, grace_seconds: int) -> str:
    match = _WATCH_INVOKE_RE.search(text)
    if match is None:
        raise StampError("_watcher_start.sh: watch invocation not found")
    flags = f" --poll-interval-seconds {poll_seconds} --transitional-grace-seconds {grace_seconds}"
    start = match.end()
    rest = text[start:]
    existing = re.match(
        r"(?:\s+--poll-interval-seconds\s+\S+)(?:\s+--transitional-grace-seconds\s+\S+)?",
        rest,
    )
    if existing is not None:
        return text[:start] + flags + rest[existing.end() :]
    return text[:start] + flags + rest


def transform_status(text: str) -> str:
    if "export DOCKER_HOST" not in text:
        export_line = f'export DOCKER_HOST="{DEFAULT_DOCKER_HOST}"\n'
        if text.startswith("#!"):
            nl = text.find("\n")
            text = text[: nl + 1] + export_line + text[nl + 1 :]
        else:
            text = export_line + text

    if "<<'PY'" in text and "jobs-overview-status.json" in text:
        return text

    snippet = status_heredoc()
    if _STATUS_ONELINER_RE.search(text):
        return _STATUS_ONELINER_RE.sub(snippet, text, count=1)
    if _STATUS_ONELINER_LINE_RE.search(text):
        return _STATUS_ONELINER_LINE_RE.sub(snippet, text, count=1)
    if "BROKEN_FLINK_REST_ONELINER" in text:
        return text.replace("BROKEN_FLINK_REST_ONELINER", snippet, 1)
    raise StampError("_status.sh: broken flink REST one-liner not found")


def rewrite_sha_pins(text: str, verify_sha: str, producer_sha: str) -> str:
    if not _VERIFY_SHA_RE.search(text):
        raise StampError("VERIFY_SHA= not found in _remote_soak_start.sh")
    if not _PRODUCER_SHA_RE.search(text):
        raise StampError("PRODUCER_SHA= not found in _remote_soak_start.sh")
    text = _VERIFY_SHA_RE.sub(f"VERIFY_SHA={verify_sha}", text, count=1)
    return _PRODUCER_SHA_RE.sub(f"PRODUCER_SHA={producer_sha}", text, count=1)


def launch_order_markdown(cfg: StampConfig, source_event: str, source_order: str) -> str:
    ident = cfg.identity
    pack = f"/tmp/soak-pack-{ident}"  # noqa: S108
    ctl = f"/tmp/agentflow-soak-ctl-{ident}"  # noqa: S108
    watcher = f"/Users/julia/agentflow-flink-watcher-{ident}"
    runtime = f"/tmp/agentflow-soak-runtime-{ident}"  # noqa: S108
    recover_out = f"/tmp/agentflow-flink-recover-{ident}"  # noqa: S108
    evidence = f"/var/agentflow-task-state/golden-4h-soak-rv-{ident}"
    return "\n".join(
        [
            f"# Soak {ident} launch order",
            "",
            "Nothing in this slice is applied to the Mac. This file is the exact",
            "remote sequence for a later executor.",
            "",
            f"**Never rerun -06.** Identity `{CONSUMED_SOURCE_NOTE}` /",
            f"`golden-4h-soak-rv-{CONSUMED_SOURCE_NOTE}` is consumed. Do not reuse its",
            "EVENT_PREFIX, ORDER_PREFIX, Jobs, ConfigMaps, watcher directory, or",
            "hostPath. A rerun needs a new identity.",
            "",
            "## Identity facts",
            "",
            f"- identity: `{ident}`",
            f"- source identity: `{cfg.source_identity}`",
            f"- RUN_LABEL: `golden-4h-soak-rv-{ident}`",
            f"- EVENT_PREFIX: `{cfg.event_prefix}` (was `{source_event}`)",
            f"- ORDER_PREFIX: `{cfg.order_prefix}` (was `{source_order}`)",
            f"- pack: `{pack}/`",
            f"- control scripts: `{ctl}/`",
            f"- watcher dir: `{watcher}/`",
            f"- runtime out: `{runtime}/`",
            f"- recover out: `{recover_out}/`",
            f"- evidence hostPath: `{evidence}`",
            f"- checkpoint interval / min-pause: `{cfg.checkpoint_interval_ms} ms` / "
            f"`{cfg.checkpoint_min_pause_ms} ms` (flinkConfiguration + matching env)",
            f"- watcher poll / transitional grace: `{cfg.watcher_poll_seconds}s` / "
            f"`{cfg.watcher_grace_seconds}s`",
            "- Kafka group unchanged: `agentflow-golden-soak-rv-20260802-01`",
            "- kind context / namespace / CR name+UID / node / ClickHouse container unchanged",
            "",
            "## SCP targets",
            "",
            f"1. `pack/*` → `{pack}/`",
            f"2. `_flink_recover.sh` `_remote_soak_start.sh` `_remote_soak_watchdog.sh` "
            f"`_status.sh` `_watcher_start.sh` → `{ctl}/`",
            f"3. `watcher/capture_flink_failure_evidence.py` → `{watcher}/`",
            "",
            "## Remote steps",
            "",
            "1. Confirm five workloads Ready and Flink SUSPENDED. Remove any stale",
            f"   `{recover_out}/result.txt`.",
            "2. Warm the operator mutating webhook with a server-side dry-run",
            "   annotation patch on FlinkDeployment `agentflow-soak-rv-stream-processor`.",
            f"3. Recover: `bash {ctl}/_flink_recover.sh`",
            "   (nonce bump, CP stretch + env-by-name rewrite, wait STABLE/RUNNING,",
            "   REST 2/2, 90 s checkpoint-growth hold, post-recover env assertion).",
            f"4. Start: `nohup bash {ctl}/_remote_soak_start.sh`",
            "   Inside start, in order: preflight → Gate A → **baseline with a 15 s",
            "   `.status.succeeded` / `.status.failed` poll (600 s budget, not",
            "   `kubectl wait`)** → **arm watcher** (`bash "
            f"{ctl}/_watcher_start.sh`, require last line `RESULT=WATCHER_ARMED`,",
            f"   record pid line in `{runtime}/watcher-armed.txt`) → observer → producer.",
            f"5. Watchdog: `nohup bash {ctl}/_remote_soak_watchdog.sh`",
            f"6. Status: `bash {ctl}/_status.sh`",
            "",
            "## Rule: no host-side kubectl polling in the first 15 min",
            "",
            "After start returns `RESULT=SOAK_RUNNING`, do not add extra host-side",
            "`kubectl` / ssh polling for the first 15 minutes. Launch API pile-up is",
            "what knocked -06 into SUSPENDED. Use the start script, the armed watcher,",
            "and the watchdog only.",
            "",
        ]
    )


def unified_diff_md(
    originals: dict[str, str],
    stamped: dict[str, str],
    new_files: dict[str, str],
) -> str:
    chunks = [
        "# Unified diff vs source mirror",
        "",
        "Generated by `difflib.unified_diff`. Sidecars `MANIFEST.json`,",
        "`DIFF_VS_SOURCE.md`, and `LAUNCH_ORDER.md` are omitted.",
        "",
    ]
    names = sorted(set(originals) | set(stamped))
    for name in names:
        old = originals.get(name, "")
        new = stamped.get(name, "")
        if old == new:
            continue
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
        )
        chunks.append(f"## `{name}`")
        chunks.append("")
        chunks.append("```diff")
        chunks.extend(line.rstrip("\n") for line in diff)
        chunks.append("```")
        chunks.append("")
    for name in sorted(new_files):
        diff = difflib.unified_diff(
            [],
            new_files[name].splitlines(keepends=True),
            fromfile="/dev/null",
            tofile=f"b/{name}",
        )
        chunks.append(f"## `{name}` (added)")
        chunks.append("")
        chunks.append("```diff")
        chunks.extend(line.rstrip("\n") for line in diff)
        chunks.append("```")
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def run_bash_n(bash: Path, script: Path) -> None:
    result = subprocess.run(
        [str(bash), "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise StampError(f"bash -n failed: {script.name}: {detail}")


def stamp(cfg: StampConfig) -> dict[str, object]:
    if not cfg.source_dir.is_dir():
        raise StampError(f"source-dir not found: {posix(cfg.source_dir)}")
    if not cfg.watcher_script.is_file():
        raise StampError(f"watcher-script not found: {posix(cfg.watcher_script)}")
    missing = missing_required(cfg.source_dir)
    if missing:
        raise StampError("missing required source files: " + ", ".join(missing))
    if cfg.out_dir.exists() and not cfg.force:
        raise StampError(
            f"refusing to overwrite existing out-dir: {posix(cfg.out_dir)} (use --force)"
        )
    if cfg.out_dir.exists() and cfg.force:
        shutil.rmtree(cfg.out_dir)

    start_src = decode_text((cfg.source_dir / "_remote_soak_start.sh").read_bytes())
    source_event = parse_assignment(start_src, "EVENT_PREFIX")
    source_order = parse_assignment(start_src, "ORDER_PREFIX")

    originals: dict[str, str] = {}
    stamped: dict[str, str] = {}
    substitutions: dict[str, dict[str, int]] = {}
    prefix_locations: dict[str, list[dict[str, object]]] = {
        "event_prefix": [],
        "order_prefix": [],
    }
    binary_files: dict[str, bytes] = {}

    for path in iter_source_files(cfg.source_dir):
        relative = posix(path.relative_to(cfg.source_dir))
        data = path.read_bytes()
        if not is_text_name(relative):
            binary_files[relative] = data
            continue
        original = decode_text(data)
        originals[relative] = original
        text, ident_n = replace_token(original, cfg.source_identity, cfg.identity)
        event_lines = locate_replacements(text, source_event)
        order_lines = locate_replacements(text, source_order)
        for line_no in event_lines:
            prefix_locations["event_prefix"].append({"file": relative, "line": line_no})
        for line_no in order_lines:
            prefix_locations["order_prefix"].append({"file": relative, "line": line_no})
        text, event_n = replace_token(text, source_event, cfg.event_prefix)
        text, order_n = replace_token(text, source_order, cfg.order_prefix)
        substitutions[relative] = {
            "identity": ident_n,
            "event_prefix": event_n,
            "order_prefix": order_n,
        }
        stamped[relative] = text

    recover_name = "_flink_recover.sh"
    start_name = "_remote_soak_start.sh"
    watcher_name = "_watcher_start.sh"
    status_name = "_status.sh"
    stamped[recover_name] = transform_recover(
        stamped[recover_name],
        cfg.checkpoint_interval_ms,
        cfg.checkpoint_min_pause_ms,
    )
    stamped[start_name] = transform_start(stamped[start_name], cfg.identity)
    stamped[watcher_name] = transform_watcher_start(
        stamped[watcher_name],
        cfg.watcher_poll_seconds,
        cfg.watcher_grace_seconds,
    )
    stamped[status_name] = transform_status(stamped[status_name])

    verify_bytes = encode_text(stamped["pack/verify.py"])
    producer_bytes = encode_text(stamped["pack/producer.py"])
    verify_sha = sha256_bytes(verify_bytes)
    producer_sha = sha256_bytes(producer_bytes)
    stamped[start_name] = rewrite_sha_pins(stamped[start_name], verify_sha, producer_sha)

    watcher_rel = "watcher/capture_flink_failure_evidence.py"
    watcher_bytes = cfg.watcher_script.read_bytes()
    watcher_text = decode_text(watcher_bytes) if is_text_name(watcher_rel) else None

    unresolved: list[str] = []
    for relative, text in stamped.items():
        if cfg.source_identity in text:
            unresolved.append(relative)
    if watcher_text is not None and cfg.source_identity in watcher_text:
        unresolved.append(watcher_rel)
    unresolved.sort()
    if unresolved:
        raise StampError("unresolved source-identity tokens remain: " + ", ".join(unresolved))

    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, bytes] = {}
    for relative, text in stamped.items():
        target = cfg.out_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = encode_text(text)
        target.write_bytes(payload)
        written[relative] = payload
    for relative, payload in binary_files.items():
        target = cfg.out_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        written[relative] = payload
    watcher_target = cfg.out_dir / watcher_rel
    watcher_target.parent.mkdir(parents=True, exist_ok=True)
    watcher_target.write_bytes(watcher_bytes)
    written[watcher_rel] = watcher_bytes

    bash = find_bash()
    bash_status = "skipped"
    if bash is not None:
        for relative in sorted(written):
            if relative.endswith(".sh"):
                run_bash_n(bash, cfg.out_dir / relative)
        bash_status = "ok"

    with tempfile.TemporaryDirectory(prefix="stamp-soak-py-compile-") as tmp:
        tmp_dir = Path(tmp)
        for relative in sorted(written):
            if not relative.endswith(".py"):
                continue
            cfile = tmp_dir / (relative.replace("/", "_") + "c")
            try:
                py_compile.compile(
                    str(cfg.out_dir / relative),
                    cfile=str(cfile),
                    doraise=True,
                )
            except py_compile.PyCompileError as exc:
                raise StampError(f"py_compile failed: {relative}: {exc}") from exc

    new_text_files: dict[str, str] = {}
    if watcher_text is not None:
        new_text_files[watcher_rel] = watcher_text
    diff_text = unified_diff_md(originals, stamped, new_text_files)
    launch_text = launch_order_markdown(cfg, source_event, source_order)
    (cfg.out_dir / "DIFF_VS_SOURCE.md").write_bytes(encode_text(diff_text))
    (cfg.out_dir / "LAUNCH_ORDER.md").write_bytes(encode_text(launch_text))
    written["DIFF_VS_SOURCE.md"] = encode_text(diff_text)
    written["LAUNCH_ORDER.md"] = encode_text(launch_text)

    files_meta: dict[str, object] = {}
    for relative in sorted(written):
        entry: dict[str, object] = {"sha256": sha256_bytes(written[relative])}
        if relative in substitutions:
            entry["substitutions"] = substitutions[relative]
        files_meta[relative] = entry

    manifest: dict[str, object] = {
        "bash_syntax_check": bash_status,
        "event_prefix": cfg.event_prefix,
        "files": files_meta,
        "identity": cfg.identity,
        "knobs": {
            "checkpoint_interval_ms": cfg.checkpoint_interval_ms,
            "checkpoint_min_pause_ms": cfg.checkpoint_min_pause_ms,
            "watcher_grace_seconds": cfg.watcher_grace_seconds,
            "watcher_poll_seconds": cfg.watcher_poll_seconds,
            "watcher_script": posix(cfg.watcher_script),
        },
        "order_prefix": cfg.order_prefix,
        "out_dir": posix(cfg.out_dir),
        "prefix_locations": prefix_locations,
        "py_compile": "ok",
        "source_dir": posix(cfg.source_dir),
        "source_event_prefix": source_event,
        "source_identity": cfg.source_identity,
        "source_order_prefix": source_order,
        "unresolved": [],
        "watcher_script_sha256": sha256_bytes(watcher_bytes),
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (cfg.out_dir / "MANIFEST.json").write_bytes(encode_text(manifest_text))
    return manifest


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--source-identity", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--event-prefix", required=True)
    parser.add_argument("--order-prefix", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--checkpoint-interval-ms", type=positive_int, default=10000)
    parser.add_argument("--checkpoint-min-pause-ms", type=positive_int, default=10000)
    parser.add_argument("--watcher-poll-seconds", type=positive_int, default=30)
    parser.add_argument("--watcher-grace-seconds", type=positive_int, default=90)
    parser.add_argument("--watcher-script", type=Path, default=Path(DEFAULT_WATCHER_SCRIPT))
    parser.add_argument("--force", action="store_true")
    return parser


def config_from_args(args: argparse.Namespace) -> StampConfig:
    if not args.event_prefix.endswith("-"):
        raise StampError("--event-prefix must end with a dash")
    if not args.source_identity.strip():
        raise StampError("--source-identity is empty")
    if not args.identity.strip():
        raise StampError("--identity is empty")
    if args.source_identity == args.identity:
        raise StampError("--identity must differ from --source-identity")
    return StampConfig(
        source_dir=args.source_dir,
        out_dir=args.out_dir,
        source_identity=args.source_identity,
        identity=args.identity,
        event_prefix=args.event_prefix,
        order_prefix=args.order_prefix,
        checkpoint_interval_ms=args.checkpoint_interval_ms,
        checkpoint_min_pause_ms=args.checkpoint_min_pause_ms,
        watcher_poll_seconds=args.watcher_poll_seconds,
        watcher_grace_seconds=args.watcher_grace_seconds,
        watcher_script=args.watcher_script,
        force=args.force,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        stamp(config_from_args(args))
    except StampError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
