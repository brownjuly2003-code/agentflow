from __future__ import annotations

import hashlib
import re
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "docs" / "evidence"
INDEX = EVIDENCE_DIR / "INDEX.md"
STATUS = ROOT / "docs" / "STATUS.md"
CLAIMS = ROOT / "config" / "project_claims.toml"

SECURITY_DEPENDENCY_HEADING = "## Security and dependency records"
ACCEPTANCE_HEADING = "## Golden topology acceptance records"
REQUIRED_FIELDS = (
    "identity",
    "date",
    "result",
    "supersedes",
    "superseded by",
    "claim boundary",
)
PROTECTED_DIGESTS = {
    "docs/evidence/security-s12-2026-07-09.md": (
        "4b2223a35e5817214171aedf988b814e2bed97a08bfaa2f817c17d5e05e9108a"
    ),
    "docs/evidence/security-runtime-image-trivy-2026-07-30.md": (
        "6bbb2ebb5ff7f98db11e4f1ceb1af099116ccba806edac2ffc1221db60238d28"
    ),
    "docs/evidence/dependency-compatibility-2026-07-30.md": (
        "79618c9eea6aa31c18a7d17558c995bd424abf620f4e901b2542d1cc3031635f"
    ),
}
CURRENT_FRESHNESS_HEADING = "## Current freshness evidence records"
REAL_PATH_FRESHNESS_RECORD = "docs/perf/freshness-e2e-realpath.md"
DEMO_FRESHNESS_RECORD = "docs/perf/freshness-benchmark.md"
CURRENT_FRESHNESS_DATES = {
    REAL_PATH_FRESHNESS_RECORD: "2026-07-09",
    DEMO_FRESHNESS_RECORD: "2026-06-06",
}
CURRENT_FRESHNESS_DIGESTS = {
    REAL_PATH_FRESHNESS_RECORD: (
        "a7715b090f1593924a5503d18ed932c92681f874083a99625f2f0f9fa7050c88"
    ),
    DEMO_FRESHNESS_RECORD: ("3a21b981c81bf7178b5c9321a13af3f1f107c03123fe15ef66adb98b9ae8feba"),
}
REAL_PATH_FRESHNESS_BOUNDARIES = (
    "single mac/colima stand",
    "revenue metric",
    "one miss",
    "not an sla",
    "demo shortcut",
    "production acceptance",
)
DEMO_FRESHNESS_BOUNDARIES = (
    "in-process duckdb shortcut",
    "pre-s7",
    "windows",
    "fakeredis",
    "kafka",
    "flink",
    "bridge",
    "clickhouse",
    "current production invalidation wiring",
    "production acceptance",
)
E4_REPLICA_HEADING = "## E4 replica-correctness evidence records"
E4_TWO_POD_RECORD = "docs/perf/e4-2pod-topology-2026-07-09.md"
E4_CHECK4_RECORD = "docs/perf/e4-check4-alert-single-page-2026-07-17.md"
E4_REPLICA_DATES = {
    E4_TWO_POD_RECORD: "2026-07-09",
    E4_CHECK4_RECORD: "2026-07-17",
}
E4_REPLICA_DIGESTS = {
    E4_TWO_POD_RECORD: ("39bf695eb3e7346bfc18acdb1487dfd2e8bc394ebe045b4e7bf9df721b1959ae"),
    E4_CHECK4_RECORD: ("4af1aaf1963bd1747de678a28d6d08de6733f15ef7e44cb01216ab425cf76c3a"),
}
E4_TWO_POD_BOUNDARIES = (
    "checks 1-2",
    "two ready pods",
    "postgres",
    "8 round-robin",
    "explicit a-to-b",
    "does not claim checks 3-4",
    "hq-demo",
    "production acceptance",
)
E4_CHECK4_BOUNDARIES = (
    "checks 1-4 pass",
    "exactly one delivery",
    "exactly one alert",
    "agentflow-staging",
    "local pre-push",
    "httpbin",
    "durable persistence",
    "production acceptance",
)
HISTORICAL_E4_HEADING = "## Historical E4 intermediate replica-correctness records"
E4_REPLICA_TOPOLOGY_RECORD = "docs/perf/e4-replica-topology-2026-07-11.md"
E4_CHECK3_RECORD = "docs/perf/e4-check3-exactly-one-delivery-2026-07-16.md"
HISTORICAL_E4_DATES = {
    E4_REPLICA_TOPOLOGY_RECORD: "2026-07-11",
    E4_CHECK3_RECORD: "2026-07-16",
}
HISTORICAL_E4_DIGESTS = {
    E4_REPLICA_TOPOLOGY_RECORD: (
        "dcab8c990386afa3dff065fb07be2195cc40bb20d0328c0f1441b2d7c148a571"
    ),
    E4_CHECK3_RECORD: ("6bf8d6773997e69d1634eddcb3a7fdf2aa881a404af360e7d762ed22ca283bf8"),
}
E4_REPLICA_TOPOLOGY_BOUNDARIES = (
    "historical",
    "intermediate",
    "checks 1-2",
    "agentflow-staging",
    "2026-07-06",
    "9935bdc",
    "does not claim checks 3-4",
    "exactly-one delivery",
    "alert single-page",
    "hq-demo",
    "a-to-b",
    "production acceptance",
    "candidate",
)
E4_CHECK3_BOUNDARIES = (
    "historical",
    "intermediate",
    "checks 1-3 pass",
    "exactly one delivery",
    "replica-e4-858cce874ac04494",
    "22fbae6",
    "delivery half",
    "does not claim check 4",
    "alert single-page",
    "not a current status owner",
    "production acceptance",
    "candidate",
)
CURRENT_ENDURANCE_SCALE_HEADING = "## Current endurance and scale evidence records"
S11_SOAK_RECORD = "docs/perf/soak-s11-2026-07-10.md"
S13_SCALE_RECORD = "docs/perf/scale-own-data-2026-07-11.md"
RSS_REVERIFY_RECORD = "docs/perf/rss-reverify-183-2026-07-11.md"
CURRENT_ENDURANCE_SCALE_DATES = {
    S11_SOAK_RECORD: "2026-07-10",
    S13_SCALE_RECORD: "2026-07-11",
}
CURRENT_ENDURANCE_SCALE_DIGESTS = {
    S11_SOAK_RECORD: ("040e3f2c473b1a52426f0d4e77cefa2dc26e35fe3db09d1c453697eb9f1eaf91"),
    S13_SCALE_RECORD: ("cebea4fe43c31380f589cf7e5dcf8706ef20314f1f2d104cb6ed06c8c52c6e5b"),
}
S11_STATUS_CLAIM = "4 h endurance soak (real path + API reads)"
S11_STATUS_RESULT = (
    "bounded lag (peak 2 915 → 0), bridge RSS/FD flat, one faulted batch "
    "replayed exactly-once by the journal guard, **zero cache drift**"
)
S13_STATUS_CLAIM = "At-scale on own data (S13)"
S13_STATUS_RESULT = (
    "**51.2 M rows / 2.87 M orders / 4 years of legend history**, analyst "
    "queries 20–730 ms, all 17 at-scale correctness checks pass"
)
S11_SOAK_BOUNDARIES = (
    "4 h",
    "real-path",
    "api-read",
    "deproject-mac",
    "colima",
    "bounded",
    "2 915",
    "journal guard",
    "exactly-once",
    "zero cache drift",
    "1 540 429 855.37",
    "682 679",
    "rss-reverify-183-2026-07-11",
    "scoped partial supersession",
    "api rss",
    "175 mb",
    "1.67 gb",
    "not a production sla",
    "production acceptance",
    "candidate",
)
S13_SCALE_BOUNDARIES = (
    "51.2 m rows",
    "2.87 m orders",
    "4 years",
    "20–730 ms",
    "17 at-scale",
    "in-database",
    "single-node",
    "laptop-class",
    "not streaming",
    "demo-scale",
    "production sla",
    "production acceptance",
    "candidate",
)
CURRENT_S10_THROUGHPUT_HEADING = "## Current S10 throughput evidence records"
S10_BURST_BASELINE_RECORD = "docs/perf/throughput-realpath.md"
S10_PACED_R4_RECORD = "docs/perf/throughput-realpath-paced100-4h-r4-2026-07-19.md"
S10_PACED_R1_RECORD = "docs/perf/throughput-realpath-paced100-4h-2026-07-18.md"
S10_PACED_R3_RECORD = "docs/perf/throughput-realpath-paced100-4h-r3-2026-07-19.md"
S10_Q12_RECORD = "docs/perf/throughput-realpath-q12-2026-07-09.md"
S10_Q13_RECORD = "docs/perf/throughput-realpath-q13-2026-07-09.md"
S10_Q14_RECORD = "docs/perf/throughput-realpath-q14-2026-07-10.md"
S10_100EPS_TRY_RECORD = "docs/perf/throughput-realpath-100eps-try-2026-07-17.md"
S10_PACED_10M_RECORD = "docs/perf/throughput-realpath-paced100-2026-07-17.md"
S10_PACED_1H_RECORD = "docs/perf/throughput-realpath-paced100-1h-2026-07-17.md"
CURRENT_S10_THROUGHPUT_DATES = {
    S10_BURST_BASELINE_RECORD: "2026-07-09",
    S10_PACED_R4_RECORD: "2026-07-19",
}
CURRENT_S10_THROUGHPUT_DIGESTS = {
    S10_BURST_BASELINE_RECORD: ("ab6c459064593ff092c6b7bf1ab4050357ee202d63ec9ca6b9608ab978816174"),
    S10_PACED_R4_RECORD: ("08027f210934070053de3cdabd3065d7bb0a0dc8d5a9387b77880b45cd6adbda"),
}
S10_INTERMEDIATE_RECORDS = (
    S10_Q12_RECORD,
    S10_Q13_RECORD,
    S10_Q14_RECORD,
    S10_100EPS_TRY_RECORD,
    S10_PACED_10M_RECORD,
    S10_PACED_1H_RECORD,
    S10_PACED_R1_RECORD,
    S10_PACED_R3_RECORD,
)
S10_BASELINE_STATUS_HEADING = "## Proven"
S10_BASELINE_STATUS_CLAIM = "Real-path throughput measured"
S10_BASELINE_STATUS_RESULT = "produce ~700 eps; bridge apply is the ceiling (see below)"
S10_R4_STATUS_HEADING = "## Bridge write-path throughput — drain ceiling measured"
S10_R4_STATUS_CLAIM = "Paced **4 h** @ 100 eps produce (r4)"
S10_R4_STATUS_RESULT = (
    "**99.9 apply / 99.9 flink / 100.0 produce** — 1 440 000 events, "
    "dup = 0, failures = 0, lag 0 → 0, 0 Flink restarts"
)
S10_BURST_BASELINE_BOUNDARIES = (
    "pre-q1.2",
    "canonical s10",
    "burst",
    "400",
    "699",
    "7.97",
    "deproject-mac",
    "colima",
    "later best sustained",
    "current freshness headline",
    "not a direct supersession chain",
    "production sla",
    "production acceptance",
    "candidate",
)
S10_PACED_R4_BOUNDARIES = (
    "four-hour",
    "paced",
    "serving-path",
    "1 440 000",
    "100.0",
    "99.9",
    "produced",
    "delivered",
    "duplicates 0",
    "apply failures 0",
    "1956",
    "484/484",
    "never restarted",
    "current four-hour paced-gate outcome",
    "historical facts remain valid",
    "already-closed serving-path gate",
    "golden full-soak",
    "remains open",
    "blocked_host_capacity",
    "pre-materializer",
    "does not merge",
    "not a direct supersession chain",
    "production acceptance",
    "candidate",
)
GOLDEN_ACCEPTANCE_DIGESTS = {
    "docs/perf/golden-flink-submission-2026-07-30.md": (
        "f1494f0f7664816e8be01151af2406e82bcab9a4348af30839dcead039112f21"
    ),
    "docs/perf/golden-operator-acceptance-2026-07-30.md": (
        "31ba968526adab529b93b55440aab3d5e0037c60f83d44ebb5bebfbeeedaa861"
    ),
    "docs/perf/live-iceberg-materialization-2026-08-01.md": (
        "a155f2f10b57acd00d5d74f80c36afdd04a3a501513e3e3dcb806a4c65b0ecc2"
    ),
    "docs/perf/full-lake-to-serving-e2e-2026-08-01.md": (
        "0ffa18a977c4ee3ac96f02a0b57046c26197b9c3796cc88ba672b477e204312b"
    ),
}
GOLDEN_ACCEPTANCE_DATE = "2026-07-30"
LAKE_TO_SERVING_DATE = "2026-08-01"
SUBMISSION_RECORD = "docs/perf/golden-flink-submission-2026-07-30.md"
OPERATOR_RECORD = "docs/perf/golden-operator-acceptance-2026-07-30.md"
ICEBERG_RECORD = "docs/perf/live-iceberg-materialization-2026-08-01.md"
LAKE_TO_SERVING_RECORD = "docs/perf/full-lake-to-serving-e2e-2026-08-01.md"
SUBMISSION_COMMIT = "ca82be5a84a58ae37dd71ef80e785deb8e70dcad"
OPERATOR_COMMIT = "36ed1ecc250ac6c82ccc6f27de1b76a301b17a41"
ICEBERG_RUNTIME = "ed03fc47"
OPERATOR_STAND = "36ed1ec"
GOLDEN_ACCEPTANCE_DATES = {
    SUBMISSION_RECORD: GOLDEN_ACCEPTANCE_DATE,
    OPERATOR_RECORD: GOLDEN_ACCEPTANCE_DATE,
    ICEBERG_RECORD: LAKE_TO_SERVING_DATE,
    LAKE_TO_SERVING_RECORD: LAKE_TO_SERVING_DATE,
}
UNCLAIMED_BOUNDARIES = (
    "full lake-to-serving production e2e",
    "restore/replay",
    "fresh 4h soak plus rollback after traffic",
    "external penetration test",
    "production acceptance",
)
ICEBERG_UNCLAIMED_BOUNDARIES = (
    "kafka source",
    "clickhouse/api",
    "restore/replay",
    "fresh soak or rollback",
    "external penetration test",
    "npm approval",
    "operator acceptance of ed03fc47",
    "production acceptance",
)
LAKE_TO_SERVING_UNCLAIMED_BOUNDARIES = (
    "same-sha operator acceptance",
    "multi-tenant acceptance",
    "restore/replay",
    "fresh soak or rollback",
    "external penetration test",
    "npm approval",
    "production acceptance",
)
CHECKPOINT_READINESS_HEADING = "## Checkpoint and readiness acceptance records"
CHECKPOINT_RECORD = "docs/perf/checkpoint-restore-replay-2026-08-02.md"
READINESS_RECORD = "docs/perf/ready-baselined-checkpoint-hold-2026-08-03.md"
CHECKPOINT_BLOCKER_RECORD = "docs/perf/checkpoint-restore-replay-capacity-blocker-2026-08-01.md"
CANARY_TRAFFIC_RECORD = "docs/perf/golden-4h-soak-canary-failure-2026-08-02.md"
CHECKPOINT_DATE = "2026-08-02"
READINESS_DATE = "2026-08-03"
CHECKPOINT_RUNTIME = "ed03fc47"
CHECKPOINT_TTL_SECONDS = "565"
READINESS_HOLD_SECONDS = "930"
READINESS_COMPLETED_FROM = "7675"
READINESS_COMPLETED_TO = "8614"
STARTUP_FAILURE_CAUSE = "NOT_ALL_REQUIRED_TASKS_RUNNING"
CHECKPOINT_READINESS_DATES = {
    CHECKPOINT_RECORD: CHECKPOINT_DATE,
    READINESS_RECORD: READINESS_DATE,
}
CHECKPOINT_READINESS_DIGESTS = {
    CHECKPOINT_RECORD: ("310e71a056393b6f174d2138438b47a69ea7421ee69c41076da23ee64ef65161"),
    READINESS_RECORD: ("183d001e511a6e333edde00d5d738785d8f35a4d33aa5c602195116275659952"),
}
CHECKPOINT_BLOCKER_DIGEST = "b1288e175d29909f2599d1802a24968098e196851168ff9c032cd21697e0a944"
CHECKPOINT_UNCLAIMED_BOUNDARIES = (
    "four-hour soak",
    "helm rollback",
    "same-sha",
    "external penetration",
    "npm",
    "production acceptance",
)
READINESS_UNCLAIMED_BOUNDARIES = (
    "canary2",
    "four-hour soak",
    "rollback",
    "external penetration",
    "production acceptance",
)
F10_HEADING = "## F-10 rollback and soak-capacity records (2026-08-23)"
ROLLBACK_RECORD = "corrected-rollback-pair-runtime-20260823-01.md"
SOAK_CAPACITY_RECORD = "ci-soak-f02-capacity-decision-20260823-01.md"
PROJECT_CLOSURE = ROOT / "docs" / "PROJECT_CLOSURE.md"
F10_DATE = "2026-08-23"
F10_DATES = {
    ROLLBACK_RECORD: F10_DATE,
    SOAK_CAPACITY_RECORD: F10_DATE,
}
F10_DIGESTS = {
    ROLLBACK_RECORD: ("fc963bd0062a5b41ca13edfd640df0f497fcde8d8030ff1d23387980c6e84fae"),
    SOAK_CAPACITY_RECORD: ("f6e3f906f449816d4fb7a583a4b64ac724c56be794203837608ddbd6f43d3fe9"),
}
F10_SHARED_UNCLAIMED_BOUNDARIES = (
    "fresh four-hour soak plus rollback after traffic",
    "production acceptance",
    "deploy",
    "publication",
)
KIND_SOAK_HEADING = "## Kind-residual canary and latest soak records"
KIND_RESIDUAL_RECORD = "docs/perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md"
SOAK_05_RECORD = "docs/perf/golden-4h-soak-05-failure-2026-08-08.md"
SOAK_START_RECORD = "docs/perf/golden-4h-soak-start-2026-08-07.md"
KIND_RESIDUAL_DATE = "2026-08-07"
SOAK_05_DATE = "2026-08-08"
KIND_SOAK_DATES = {
    KIND_RESIDUAL_RECORD: KIND_RESIDUAL_DATE,
    SOAK_05_RECORD: SOAK_05_DATE,
}
KIND_SOAK_DIGESTS = {
    KIND_RESIDUAL_RECORD: ("86715d0b29a36f2d5669099e6b85aeceb3abadce7fab7d82f239bf6062f9c1e9"),
    SOAK_05_RECORD: ("30c95061ce0596aeb9612027f47919a9f4f4e22a168a3f25ff70dee7a465a202"),
}
SOAK_START_DIGEST = "cfec64254a5d35f7d3124441ad20784a81b69b3907a27be64cf2062fbb7251ec"
CANARY_TRAFFIC_DIGEST = "fa9460c0c7af678546680c6a9889780fc51b4abf492025878daeee5648b30adc"
KIND_RESIDUAL_UNCLAIMED_BOUNDARIES = (
    "dual-mean >=90",
    "four-hour soak",
    "helm rollback",
    "production acceptance",
)
SOAK_UNCLAIMED_BOUNDARIES = (
    "soak pass",
    "dual-mean pass",
    "rollback pass",
    "production acceptance",
)
HISTORICAL_CANARY_SOAK_HEADING = "## Historical canary-failure and soak-start records"
RESOURCE_BLOCKER_RECORD = "docs/perf/golden-4h-soak-rollback-resource-blocker-2026-08-01.md"
CANARY_TRAFFIC_DATE = "2026-08-02"
SOAK_START_DATE = "2026-08-07"
HISTORICAL_CANARY_SOAK_DATES = {
    CANARY_TRAFFIC_RECORD: CANARY_TRAFFIC_DATE,
    SOAK_START_RECORD: SOAK_START_DATE,
}
HISTORICAL_CANARY_SOAK_DIGESTS = {
    CANARY_TRAFFIC_RECORD: CANARY_TRAFFIC_DIGEST,
    SOAK_START_RECORD: SOAK_START_DIGEST,
}
RESOURCE_BLOCKER_DIGEST = "3504c46afc276d5725576bcc0a1caa2415cf02e6b6bb3febe8e9fc22a070b8d5"
CANARY_FAILURE_UNCLAIMED_BOUNDARIES = (
    "four-hour soak",
    "rollback",
    "production acceptance",
)
SOAK_START_UNCLAIMED_BOUNDARIES = (
    "soak pass",
    "mean >=90",
    "rollback pass",
    "production acceptance",
)
HISTORICAL_CAPACITY_BLOCKERS_HEADING = "## Historical capacity-blocker records"
CAPACITY_BLOCKER_DATE = "2026-08-01"
HISTORICAL_CAPACITY_BLOCKER_DATES = {
    CHECKPOINT_BLOCKER_RECORD: CAPACITY_BLOCKER_DATE,
    RESOURCE_BLOCKER_RECORD: CAPACITY_BLOCKER_DATE,
}
HISTORICAL_CAPACITY_BLOCKER_DIGESTS = {
    CHECKPOINT_BLOCKER_RECORD: CHECKPOINT_BLOCKER_DIGEST,
    RESOURCE_BLOCKER_RECORD: RESOURCE_BLOCKER_DIGEST,
}
CHECKPOINT_BLOCKER_UNCLAIMED_BOUNDARIES = (
    "restore/replay acceptance",
    "e1/e2",
    "ttl",
    "four-hour soak",
    "rollback",
    "production acceptance",
)
SOAK_RESOURCE_BLOCKER_UNCLAIMED_BOUNDARIES = (
    "canary",
    "four-hour soak",
    "rollback",
    "checkpoint restore/replay",
    "production acceptance",
)

LINK_RE = re.compile(r"\[[^]]+\]\(([^)#?]+\.md)\)")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")


def _section(text: str, heading: str) -> str:
    start = text.index(heading) + len(heading)
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start:end]


def _normalize_field(cell: str) -> str:
    return re.sub(r"[\s_-]+", " ", cell.strip().lower())


def _markdown_table(section: str) -> tuple[list[str], list[list[str]]]:
    raw_rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        raw_rows.append(cells)

    assert raw_rows, "section has no Markdown table"
    headers = [_normalize_field(cell) for cell in raw_rows[0]]
    body = raw_rows[1:]
    if body and all(SEPARATOR_CELL_RE.fullmatch(cell.replace(" ", "")) for cell in body[0]):
        body = body[1:]
    return headers, body


def _rows_for_heading(heading: str) -> list[dict[str, str]]:
    section = _section(INDEX.read_text(encoding="utf-8"), heading)
    headers, body = _markdown_table(section)
    rows: list[dict[str, str]] = []
    for cells in body:
        assert len(cells) == len(headers), (
            f"expected {len(headers)} columns, got {len(cells)}: {cells!r}"
        )
        rows.append(dict(zip(headers, cells, strict=True)))
    assert rows, f"{heading} table has no data rows"
    return rows


def _security_dependency_rows() -> list[dict[str, str]]:
    return _rows_for_heading(SECURITY_DEPENDENCY_HEADING)


def _current_freshness_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CURRENT_FRESHNESS_HEADING)


def _current_freshness_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _current_freshness_rows()]


def _e4_replica_rows() -> list[dict[str, str]]:
    return _rows_for_heading(E4_REPLICA_HEADING)


def _e4_replica_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _e4_replica_rows()]


def _historical_e4_rows() -> list[dict[str, str]]:
    return _rows_for_heading(HISTORICAL_E4_HEADING)


def _historical_e4_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _historical_e4_rows()]


def _current_endurance_scale_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CURRENT_ENDURANCE_SCALE_HEADING)


def _current_endurance_scale_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _current_endurance_scale_rows()]


def _current_s10_throughput_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CURRENT_S10_THROUGHPUT_HEADING)


def _current_s10_throughput_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _current_s10_throughput_rows()]


def _status_table_rows(heading: str) -> list[dict[str, str]]:
    section = _section(STATUS.read_text(encoding="utf-8"), heading)
    headers, body = _markdown_table(section)
    rows: list[dict[str, str]] = []
    for cells in body:
        assert len(cells) == len(headers), (
            f"expected {len(headers)} columns, got {len(cells)}: {cells!r}"
        )
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _status_cell_record_paths(cell: str) -> list[str]:
    return [
        (STATUS.parent / target).resolve().relative_to(ROOT).as_posix()
        for target in LINK_RE.findall(cell)
    ]


def _acceptance_rows() -> list[dict[str, str]]:
    return _rows_for_heading(ACCEPTANCE_HEADING)


def _on_disk_evidence_records() -> set[str]:
    return {
        path.relative_to(ROOT).as_posix()
        for path in EVIDENCE_DIR.glob("*.md")
        if path.name != "INDEX.md"
    }


def _resolve_index_link(target: str) -> str:
    return (INDEX.parent / target).resolve().relative_to(ROOT).as_posix()


def _identity_path(cell: str) -> str:
    matches = LINK_RE.findall(cell)
    assert matches, f"identity cell has no markdown path: {cell!r}"
    assert len(matches) == 1, f"identity cell must name one record: {cell!r}"
    return _resolve_index_link(matches[0])


def _indexed_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _security_dependency_rows()]


def _acceptance_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _acceptance_rows()]


def _checkpoint_readiness_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CHECKPOINT_READINESS_HEADING)


def _checkpoint_readiness_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _checkpoint_readiness_rows()]


def _f10_rows() -> list[dict[str, str]]:
    return _rows_for_heading(F10_HEADING)


def _f10_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _f10_rows()]


def _kind_soak_rows() -> list[dict[str, str]]:
    return _rows_for_heading(KIND_SOAK_HEADING)


def _kind_soak_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _kind_soak_rows()]


def _historical_canary_soak_rows() -> list[dict[str, str]]:
    return _rows_for_heading(HISTORICAL_CANARY_SOAK_HEADING)


def _historical_canary_soak_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _historical_canary_soak_rows()]


def _historical_capacity_blocker_rows() -> list[dict[str, str]]:
    return _rows_for_heading(HISTORICAL_CAPACITY_BLOCKERS_HEADING)


def _historical_capacity_blocker_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _historical_capacity_blocker_rows()]


def _project_closure_record_links() -> set[str]:
    found: set[str] = set()
    for target in LINK_RE.findall(PROJECT_CLOSURE.read_text(encoding="utf-8")):
        resolved = (PROJECT_CLOSURE.parent / target).resolve()
        try:
            found.add(resolved.relative_to(ROOT).as_posix())
        except ValueError:
            continue
    return found


def _status_record_links() -> set[str]:
    found: set[str] = set()
    for target in LINK_RE.findall(STATUS.read_text(encoding="utf-8")):
        resolved = (STATUS.parent / target).resolve()
        try:
            found.add(resolved.relative_to(ROOT).as_posix())
        except ValueError:
            continue
    return found


def _row_text(row: dict[str, str]) -> str:
    return f"{row.get('result', '')} {row.get('claim boundary', '')}".lower()


def _status_evidence_links() -> set[str]:
    found: set[str] = set()
    for target in LINK_RE.findall(STATUS.read_text(encoding="utf-8")):
        resolved = (STATUS.parent / target).resolve()
        try:
            relative = resolved.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if Path(relative).parent.as_posix() != "docs/evidence":
            continue
        if Path(relative).name == "INDEX.md":
            continue
        found.add(relative)
    return found


def _assert_supersession_cell(cell: str) -> None:
    if cell == "None":
        return
    targets = LINK_RE.findall(cell)
    remainder = LINK_RE.sub("", cell).strip()
    assert targets, f"supersession cell invents an unnamed target: {cell!r}"
    assert remainder == "", f"supersession cell has unnamed leftover text: {cell!r}"
    for target in targets:
        path = ROOT / _resolve_index_link(target)
        assert path.is_file(), f"supersession target does not exist: {target!r}"


def test_security_dependency_index_lists_each_evidence_record_once() -> None:
    indexed = _indexed_record_paths()
    on_disk = _on_disk_evidence_records()

    assert set(indexed) == on_disk
    assert Counter(indexed) == Counter(on_disk)


def test_security_dependency_index_exposes_required_nonempty_fields() -> None:
    rows = _security_dependency_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]


def test_status_evidence_links_match_indexed_records() -> None:
    indexed = set(_indexed_record_paths())

    assert indexed == _status_evidence_links()
    assert indexed == _on_disk_evidence_records()


def test_protected_evidence_records_keep_published_digests() -> None:
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_supersession_fields_are_none_or_existing_paths() -> None:
    for row in _security_dependency_rows():
        _assert_supersession_cell(row.get("supersedes", ""))
        _assert_supersession_cell(row.get("superseded by", ""))


def test_golden_acceptance_index_lists_the_bounded_pair_once() -> None:
    indexed = _acceptance_record_paths()
    expected = (
        SUBMISSION_RECORD,
        OPERATOR_RECORD,
        ICEBERG_RECORD,
        LAKE_TO_SERVING_RECORD,
    )

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 4
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed[:2] == [SUBMISSION_RECORD, OPERATOR_RECORD]


def test_golden_acceptance_index_exposes_required_nonempty_fields() -> None:
    rows = _acceptance_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 4
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == GOLDEN_ACCEPTANCE_DATES[identity]


def test_golden_acceptance_supersession_is_none() -> None:
    for row in _acceptance_rows():
        assert row.get("supersedes", "") == "None"
        assert row.get("superseded by", "") == "None"
        _assert_supersession_cell(row.get("supersedes", ""))
        _assert_supersession_cell(row.get("superseded by", ""))


def test_golden_acceptance_records_keep_published_digests() -> None:
    indexed = set(_acceptance_record_paths())

    assert indexed == set(GOLDEN_ACCEPTANCE_DIGESTS)
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_golden_acceptance_claim_links_match_indexed_records() -> None:
    indexed = set(_acceptance_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()

    assert indexed == {
        SUBMISSION_RECORD,
        OPERATOR_RECORD,
        ICEBERG_RECORD,
        LAKE_TO_SERVING_RECORD,
    }
    assert production.get("verified_submission_smoke") == SUBMISSION_RECORD
    assert production.get("verified_operator_acceptance") == OPERATOR_RECORD
    assert production.get("verified_iceberg_materialization") == ICEBERG_RECORD
    assert production.get("verified_full_lake_to_serving_smoke") == LAKE_TO_SERVING_RECORD
    assert production.get("status") == "candidate"
    assert SUBMISSION_RECORD in manifest["required_evidence"]
    assert OPERATOR_RECORD in manifest["required_evidence"]
    assert ICEBERG_RECORD in manifest["required_evidence"]
    assert LAKE_TO_SERVING_RECORD in manifest["required_evidence"]
    assert SUBMISSION_RECORD in status_links
    assert OPERATOR_RECORD in status_links
    assert ICEBERG_RECORD in status_links
    assert LAKE_TO_SERVING_RECORD in status_links


def test_golden_acceptance_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _acceptance_rows()}
    submission = _row_text(rows[SUBMISSION_RECORD])
    operator = _row_text(rows[OPERATOR_RECORD])
    iceberg = _row_text(rows[ICEBERG_RECORD])
    lake_to_serving = _row_text(rows[LAKE_TO_SERVING_RECORD])

    assert "pass" in rows[SUBMISSION_RECORD]["result"].lower()
    assert "clean-checkout" in submission
    assert "oci" in submission
    assert "submission" in submission
    assert "running" in submission
    assert SUBMISSION_COMMIT in submission
    assert "pass" in rows[OPERATOR_RECORD]["result"].lower()
    assert "kind" in operator
    assert "operator" in operator
    assert "helm" in operator
    assert "hold" in operator
    assert OPERATOR_COMMIT in operator
    assert "pass" in rows[ICEBERG_RECORD]["result"].lower()
    assert "events.validated" in iceberg
    assert ICEBERG_RUNTIME in iceberg
    assert "lake materializer" in iceberg
    assert "iceberg" in iceberg
    assert "match_count=1" in iceberg
    assert OPERATOR_STAND in iceberg
    assert "pass" in rows[LAKE_TO_SERVING_RECORD]["result"].lower()
    assert "mixed-sha" in lake_to_serving
    assert "orders.raw" in lake_to_serving
    assert OPERATOR_STAND in lake_to_serving
    assert "pyflink" in lake_to_serving
    assert "events.validated" in lake_to_serving
    assert "iceberg" in lake_to_serving
    assert "bridge" in lake_to_serving
    assert "clickhouse" in lake_to_serving
    assert "task api" in lake_to_serving
    assert ICEBERG_RUNTIME in lake_to_serving
    for text in (submission, operator, iceberg, lake_to_serving):
        assert "does not claim" in text
        assert "candidate" in text
    for text in (submission, operator):
        for phrase in UNCLAIMED_BOUNDARIES:
            assert phrase in text
    for phrase in ICEBERG_UNCLAIMED_BOUNDARIES:
        assert phrase in iceberg
    for phrase in LAKE_TO_SERVING_UNCLAIMED_BOUNDARIES:
        assert phrase in lake_to_serving


def test_checkpoint_readiness_section_follows_golden_acceptance() -> None:
    text = INDEX.read_text(encoding="utf-8")
    golden_at = text.index(ACCEPTANCE_HEADING)
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    following_at = text.index("## F-10 rollback and soak-capacity records")

    assert golden_at < checkpoint_at < following_at


def test_checkpoint_readiness_index_lists_the_bounded_pair_once() -> None:
    indexed = _checkpoint_readiness_record_paths()
    expected = (CHECKPOINT_RECORD, READINESS_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [CHECKPOINT_RECORD, READINESS_RECORD]
    for row in _checkpoint_readiness_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_checkpoint_readiness_index_exposes_required_nonempty_fields() -> None:
    rows = _checkpoint_readiness_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CHECKPOINT_READINESS_DATES[identity]


def test_checkpoint_readiness_supersession_direction() -> None:
    rows = {_identity_path(row["identity"]): row for row in _checkpoint_readiness_rows()}
    checkpoint = rows[CHECKPOINT_RECORD]
    readiness = rows[READINESS_RECORD]
    supersedes_targets = LINK_RE.findall(checkpoint["supersedes"])

    assert [_resolve_index_link(target) for target in supersedes_targets] == [
        CHECKPOINT_BLOCKER_RECORD
    ]
    assert supersedes_targets[0].startswith("../perf/")
    assert checkpoint["superseded by"] == "None"
    assert readiness["supersedes"] == "None"
    assert readiness["superseded by"] == "None"
    _assert_supersession_cell(checkpoint["supersedes"])
    _assert_supersession_cell(checkpoint["superseded by"])
    _assert_supersession_cell(readiness["supersedes"])
    _assert_supersession_cell(readiness["superseded by"])
    for cell in (readiness["supersedes"], readiness["superseded by"]):
        resolved = [_resolve_index_link(target) for target in LINK_RE.findall(cell)]
        assert CHECKPOINT_RECORD not in resolved
        assert CHECKPOINT_BLOCKER_RECORD not in resolved
        assert CANARY_TRAFFIC_RECORD not in resolved


def test_checkpoint_readiness_records_keep_published_digests() -> None:
    indexed = set(_checkpoint_readiness_record_paths())

    assert indexed == set(CHECKPOINT_READINESS_DIGESTS)
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == CHECKPOINT_BLOCKER_DIGEST
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_checkpoint_readiness_claim_links_match_indexed_records() -> None:
    indexed = set(_checkpoint_readiness_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()

    assert indexed == {CHECKPOINT_RECORD, READINESS_RECORD}
    assert production.get("verified_checkpoint_restore_replay") == CHECKPOINT_RECORD
    assert production.get("verified_ready_baselined_checkpoint_hold") == (READINESS_RECORD)
    assert production.get("latest_soak_recovery_evidence") == READINESS_RECORD
    assert production.get("status") == "candidate"
    assert CHECKPOINT_RECORD in manifest["required_evidence"]
    assert READINESS_RECORD in manifest["required_evidence"]
    assert CHECKPOINT_RECORD in status_links
    assert READINESS_RECORD in status_links


def test_checkpoint_readiness_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _checkpoint_readiness_rows()}
    checkpoint = _row_text(rows[CHECKPOINT_RECORD])
    readiness = _row_text(rows[READINESS_RECORD])

    assert "pass" in rows[CHECKPOINT_RECORD]["result"].lower()
    assert "isolated" in checkpoint
    assert "checkpoint" in checkpoint
    assert "savepoint" in checkpoint
    assert "restore" in checkpoint
    assert CHECKPOINT_RUNTIME in checkpoint
    assert "byte-identical" in checkpoint
    assert "e1" in checkpoint
    assert "e2" in checkpoint
    assert "kafka validated" in checkpoint
    assert "iceberg" in checkpoint
    assert "clickhouse" in checkpoint
    assert "api" in checkpoint
    assert "dlq" in checkpoint
    assert "lag" in checkpoint
    assert CHECKPOINT_TTL_SECONDS in checkpoint
    assert "runtime_hold_pass" in rows[READINESS_RECORD]["result"].lower()
    assert READINESS_HOLD_SECONDS in readiness
    assert "readiness-baselined" in readiness
    assert "read-only" in readiness
    assert "no-traffic" in readiness
    assert "already-running" in readiness
    assert READINESS_COMPLETED_FROM in readiness
    assert READINESS_COMPLETED_TO in readiness
    assert "failed checkpoints 1 to 1" in readiness
    assert STARTUP_FAILURE_CAUSE.lower() in readiness
    assert "does not claim" in checkpoint
    assert "does not prove" in readiness
    assert "candidate" in checkpoint
    assert "candidate" in readiness
    assert "canary" in readiness
    assert "latest traffic" in readiness
    for phrase in CHECKPOINT_UNCLAIMED_BOUNDARIES:
        assert phrase in checkpoint
    for phrase in READINESS_UNCLAIMED_BOUNDARIES:
        assert phrase in readiness


def test_f10_section_follows_checkpoint_readiness() -> None:
    text = INDEX.read_text(encoding="utf-8")
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    f10_at = text.index(F10_HEADING)

    assert checkpoint_at < f10_at


def test_f10_section_keeps_root_path_stability() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), F10_HEADING)

    assert "`docs/STATUS.md`" in section
    assert "`docs/PROJECT_CLOSURE.md`" in section
    assert "`config/project_claims.toml`" in section
    assert "root-path stability" in section
    assert "not new evidence under `docs/evidence/`" in section


def test_f10_index_lists_the_bounded_pair_once() -> None:
    indexed = _f10_record_paths()
    expected = (ROLLBACK_RECORD, SOAK_CAPACITY_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [ROLLBACK_RECORD, SOAK_CAPACITY_RECORD]
    for row in _f10_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../../"), row["identity"]


def test_f10_index_exposes_required_nonempty_fields() -> None:
    rows = _f10_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == F10_DATES[identity]


def test_f10_supersession_is_none() -> None:
    rows = {_identity_path(row["identity"]): row for row in _f10_rows()}
    rollback = rows[ROLLBACK_RECORD]
    soak = rows[SOAK_CAPACITY_RECORD]

    assert rollback["supersedes"] == "None"
    assert rollback["superseded by"] == "None"
    assert soak["supersedes"] == "None"
    assert soak["superseded by"] == "None"
    for row in (rollback, soak):
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])
        resolved_supersedes = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["supersedes"])
        ]
        resolved_superseded_by = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["superseded by"])
        ]
        assert ROLLBACK_RECORD not in resolved_supersedes
        assert SOAK_CAPACITY_RECORD not in resolved_supersedes
        assert ROLLBACK_RECORD not in resolved_superseded_by
        assert SOAK_CAPACITY_RECORD not in resolved_superseded_by


def test_f10_records_keep_published_digests() -> None:
    indexed = set(_f10_record_paths())

    assert indexed == set(F10_DIGESTS)
    for relative, expected in F10_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == CHECKPOINT_BLOCKER_DIGEST


def test_f10_claim_links_match_indexed_records() -> None:
    indexed = set(_f10_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()
    closure_links = _project_closure_record_links()

    assert indexed == {ROLLBACK_RECORD, SOAK_CAPACITY_RECORD}
    assert production.get("rollback_mechanics_evidence") == ROLLBACK_RECORD
    assert production.get("rollback_mechanics") == "PASS"
    assert production.get("full_soak_plus_rollback_after_traffic_evidence") == (
        SOAK_CAPACITY_RECORD
    )
    assert production.get("full_soak_plus_rollback_after_traffic") == ("BLOCKED_HOST_CAPACITY")
    assert production.get("status") == "candidate"
    assert ROLLBACK_RECORD in manifest["required_evidence"]
    assert SOAK_CAPACITY_RECORD in manifest["required_evidence"]
    assert ROLLBACK_RECORD in status_links
    assert SOAK_CAPACITY_RECORD in status_links
    assert ROLLBACK_RECORD in closure_links
    assert SOAK_CAPACITY_RECORD in closure_links


def test_f10_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _f10_rows()}
    rollback = _row_text(rows[ROLLBACK_RECORD])
    soak = _row_text(rows[SOAK_CAPACITY_RECORD])

    assert "pass" in rows[ROLLBACK_RECORD]["result"].lower()
    assert "rev5" in rollback
    assert "rev6" in rollback
    assert "byte-identical" in rollback
    assert "rev3" in rollback
    assert "no traffic" in rollback
    assert "blocked_host_capacity" in rows[SOAK_CAPACITY_RECORD]["result"].lower()
    assert "f-02" in soak
    assert "r17" in soak
    assert "pass" not in rows[SOAK_CAPACITY_RECORD]["result"].lower()
    assert "does not claim" in rollback
    assert "does not claim" in soak
    assert "candidate" in rollback
    assert "candidate" in soak
    for phrase in F10_SHARED_UNCLAIMED_BOUNDARIES:
        assert phrase in rollback
        assert phrase in soak


def test_kind_soak_section_follows_checkpoint_readiness() -> None:
    text = INDEX.read_text(encoding="utf-8")
    assert KIND_SOAK_HEADING in text
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    kind_soak_at = text.index(KIND_SOAK_HEADING)
    f10_at = text.index(F10_HEADING)

    assert checkpoint_at < kind_soak_at < f10_at


def test_kind_soak_index_lists_the_bounded_pair_once() -> None:
    indexed = _kind_soak_record_paths()
    expected = (KIND_RESIDUAL_RECORD, SOAK_05_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [KIND_RESIDUAL_RECORD, SOAK_05_RECORD]
    for row in _kind_soak_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_kind_soak_index_exposes_required_nonempty_fields() -> None:
    rows = _kind_soak_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == KIND_SOAK_DATES[identity]


def test_kind_soak_supersession_direction() -> None:
    rows = {_identity_path(row["identity"]): row for row in _kind_soak_rows()}
    canary = rows[KIND_RESIDUAL_RECORD]
    soak = rows[SOAK_05_RECORD]
    soak_supersedes_targets = LINK_RE.findall(soak["supersedes"])

    assert canary["supersedes"] == "None"
    assert canary["superseded by"] == "None"
    assert [_resolve_index_link(target) for target in soak_supersedes_targets] == [
        SOAK_START_RECORD
    ]
    assert soak_supersedes_targets[0].startswith("../perf/")
    assert soak["superseded by"] == "None"
    _assert_supersession_cell(canary["supersedes"])
    _assert_supersession_cell(canary["superseded by"])
    _assert_supersession_cell(soak["supersedes"])
    _assert_supersession_cell(soak["superseded by"])
    for cell in (canary["supersedes"], canary["superseded by"]):
        resolved = [_resolve_index_link(target) for target in LINK_RE.findall(cell)]
        assert CANARY_TRAFFIC_RECORD not in resolved
        assert SOAK_05_RECORD not in resolved
        assert SOAK_START_RECORD not in resolved
    soak_supersedes = [
        _resolve_index_link(target) for target in LINK_RE.findall(soak["supersedes"])
    ]
    soak_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(soak["superseded by"])
    ]
    assert KIND_RESIDUAL_RECORD not in soak_supersedes
    assert CANARY_TRAFFIC_RECORD not in soak_supersedes
    assert KIND_RESIDUAL_RECORD not in soak_superseded_by
    assert CANARY_TRAFFIC_RECORD not in soak_superseded_by
    assert SOAK_START_RECORD not in soak_superseded_by


def test_kind_soak_records_keep_published_digests() -> None:
    indexed = set(_kind_soak_record_paths())

    assert indexed == set(KIND_SOAK_DIGESTS)
    for relative, expected in KIND_SOAK_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    start_digest = hashlib.sha256((ROOT / SOAK_START_RECORD).read_bytes()).hexdigest()
    assert start_digest == SOAK_START_DIGEST
    canary_fail_digest = hashlib.sha256((ROOT / CANARY_TRAFFIC_RECORD).read_bytes()).hexdigest()
    assert canary_fail_digest == CANARY_TRAFFIC_DIGEST
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == CHECKPOINT_BLOCKER_DIGEST
    for relative, expected in F10_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_kind_soak_claim_links_match_indexed_records() -> None:
    indexed = set(_kind_soak_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()
    closure_links = _project_closure_record_links()

    assert indexed == {KIND_RESIDUAL_RECORD, SOAK_05_RECORD}
    assert production.get("latest_kind_residual_canary") == KIND_RESIDUAL_RECORD
    assert production.get("latest_kind_residual_canary_result") == (
        "pass-residual-7p51s-budget-20s"
    )
    assert production.get("latest_soak_attempt") == SOAK_05_RECORD
    assert production.get("latest_soak_attempt_result") == (
        "soak-fail-unresolved-flink-terminal-failure"
    )
    assert production.get("status") == "candidate"
    assert KIND_RESIDUAL_RECORD in manifest["required_evidence"]
    assert SOAK_05_RECORD in manifest["required_evidence"]
    assert SOAK_START_RECORD in manifest["required_evidence"]
    assert KIND_RESIDUAL_RECORD in status_links
    assert SOAK_05_RECORD in status_links
    assert SOAK_05_RECORD in closure_links


def test_kind_soak_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _kind_soak_rows()}
    canary = _row_text(rows[KIND_RESIDUAL_RECORD])
    soak = _row_text(rows[SOAK_05_RECORD])

    assert "pass_kind_residual_20" in rows[KIND_RESIDUAL_RECORD]["result"].lower()
    assert "d+c1-20" in canary
    assert "7.5127 s" in canary
    assert "20 s" in canary
    assert "2000/2000" in canary
    assert "dlq" in canary
    assert "lag" in canary
    assert "applied_mean_eps=77.9059" in canary
    assert "does not claim" in canary
    assert "candidate" in canary
    assert "soak_fail" in rows[SOAK_05_RECORD]["result"].lower()
    assert "-05" in rows[SOAK_05_RECORD]["result"].lower()
    assert "1,440,000/1,440,000" in soak
    assert "zero producer failures" in soak
    assert "99.99979" in soak
    assert "failed" in soak
    assert "flink" in soak
    assert "pass json" in soak
    assert "rollback" in soak
    assert "not started" in soak
    assert "unresolved_flink_terminal_failure" in soak
    assert "evidence-retention" in soak
    assert "topology abort" in soak
    assert "does not claim" in soak
    assert "candidate" in soak
    assert "combined gate" in soak
    assert "open" in soak
    for phrase in KIND_RESIDUAL_UNCLAIMED_BOUNDARIES:
        assert phrase in canary
    for phrase in SOAK_UNCLAIMED_BOUNDARIES:
        assert phrase in soak


def test_historical_canary_soak_section_follows_checkpoint_readiness() -> None:
    text = INDEX.read_text(encoding="utf-8")
    assert HISTORICAL_CANARY_SOAK_HEADING in text
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    historical_at = text.index(HISTORICAL_CANARY_SOAK_HEADING)
    kind_soak_at = text.index(KIND_SOAK_HEADING)
    f10_at = text.index(F10_HEADING)

    assert checkpoint_at < historical_at < kind_soak_at < f10_at


def test_historical_canary_soak_index_lists_the_bounded_pair_once() -> None:
    indexed = _historical_canary_soak_record_paths()
    expected = (CANARY_TRAFFIC_RECORD, SOAK_START_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [CANARY_TRAFFIC_RECORD, SOAK_START_RECORD]
    assert KIND_RESIDUAL_RECORD not in indexed
    assert SOAK_05_RECORD not in indexed
    assert RESOURCE_BLOCKER_RECORD not in indexed
    assert CANARY_TRAFFIC_RECORD not in _kind_soak_record_paths()
    assert SOAK_START_RECORD not in _kind_soak_record_paths()
    for row in _historical_canary_soak_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_historical_canary_soak_index_exposes_required_nonempty_fields() -> None:
    rows = _historical_canary_soak_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == HISTORICAL_CANARY_SOAK_DATES[identity]


def test_historical_canary_soak_supersession_direction() -> None:
    rows = {_identity_path(row["identity"]): row for row in _historical_canary_soak_rows()}
    canary = rows[CANARY_TRAFFIC_RECORD]
    start = rows[SOAK_START_RECORD]
    canary_supersedes_targets = LINK_RE.findall(canary["supersedes"])
    start_superseded_by_targets = LINK_RE.findall(start["superseded by"])
    kind_soak_rows = {_identity_path(row["identity"]): row for row in _kind_soak_rows()}
    soak05 = kind_soak_rows[SOAK_05_RECORD]
    soak05_supersedes_targets = LINK_RE.findall(soak05["supersedes"])

    assert [_resolve_index_link(target) for target in canary_supersedes_targets] == [
        RESOURCE_BLOCKER_RECORD
    ]
    assert canary_supersedes_targets[0].startswith("../perf/")
    assert canary["superseded by"] == "None"
    assert start["supersedes"] == "None"
    assert [_resolve_index_link(target) for target in start_superseded_by_targets] == [
        SOAK_05_RECORD
    ]
    assert start_superseded_by_targets[0].startswith("../perf/")
    assert [_resolve_index_link(target) for target in soak05_supersedes_targets] == [
        SOAK_START_RECORD
    ]
    _assert_supersession_cell(canary["supersedes"])
    _assert_supersession_cell(canary["superseded by"])
    _assert_supersession_cell(start["supersedes"])
    _assert_supersession_cell(start["superseded by"])
    canary_supersedes = [
        _resolve_index_link(target) for target in LINK_RE.findall(canary["supersedes"])
    ]
    canary_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(canary["superseded by"])
    ]
    start_supersedes = [
        _resolve_index_link(target) for target in LINK_RE.findall(start["supersedes"])
    ]
    start_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(start["superseded by"])
    ]
    assert KIND_RESIDUAL_RECORD not in canary_supersedes
    assert KIND_RESIDUAL_RECORD not in canary_superseded_by
    assert SOAK_05_RECORD not in canary_supersedes
    assert SOAK_05_RECORD not in canary_superseded_by
    assert SOAK_START_RECORD not in canary_supersedes
    assert SOAK_START_RECORD not in canary_superseded_by
    assert KIND_RESIDUAL_RECORD not in start_supersedes
    assert KIND_RESIDUAL_RECORD not in start_superseded_by
    assert CANARY_TRAFFIC_RECORD not in start_supersedes
    assert CANARY_TRAFFIC_RECORD not in start_superseded_by
    assert RESOURCE_BLOCKER_RECORD not in start_supersedes
    assert RESOURCE_BLOCKER_RECORD not in start_superseded_by
    assert SOAK_START_RECORD not in start_supersedes
    assert CANARY_TRAFFIC_RECORD not in [
        _resolve_index_link(target) for target in soak05_supersedes_targets
    ]


def test_historical_canary_soak_records_keep_published_digests() -> None:
    indexed = set(_historical_canary_soak_record_paths())

    assert indexed == set(HISTORICAL_CANARY_SOAK_DIGESTS)
    for relative, expected in HISTORICAL_CANARY_SOAK_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / RESOURCE_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == RESOURCE_BLOCKER_DIGEST
    soak05_digest = hashlib.sha256((ROOT / SOAK_05_RECORD).read_bytes()).hexdigest()
    assert soak05_digest == KIND_SOAK_DIGESTS[SOAK_05_RECORD]
    kind_residual_digest = hashlib.sha256((ROOT / KIND_RESIDUAL_RECORD).read_bytes()).hexdigest()
    assert kind_residual_digest == KIND_SOAK_DIGESTS[KIND_RESIDUAL_RECORD]
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    checkpoint_blocker_digest = hashlib.sha256(
        (ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()
    ).hexdigest()
    assert checkpoint_blocker_digest == CHECKPOINT_BLOCKER_DIGEST
    for relative, expected in F10_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_historical_canary_soak_claim_links_match_indexed_records() -> None:
    indexed = set(_historical_canary_soak_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()
    closure_links = _project_closure_record_links()

    assert indexed == {CANARY_TRAFFIC_RECORD, SOAK_START_RECORD}
    assert CANARY_TRAFFIC_RECORD in manifest["required_evidence"]
    assert SOAK_START_RECORD in manifest["required_evidence"]
    assert production.get("latest_kind_residual_canary") == KIND_RESIDUAL_RECORD
    assert production.get("latest_kind_residual_canary") != CANARY_TRAFFIC_RECORD
    assert production.get("latest_soak_attempt") == SOAK_05_RECORD
    assert production.get("latest_soak_attempt") != SOAK_START_RECORD
    assert production.get("status") == "candidate"
    assert CANARY_TRAFFIC_RECORD not in status_links
    assert SOAK_START_RECORD not in status_links
    assert CANARY_TRAFFIC_RECORD not in closure_links
    assert SOAK_START_RECORD not in closure_links
    assert KIND_RESIDUAL_RECORD in status_links
    assert SOAK_05_RECORD in status_links


def test_historical_canary_soak_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _historical_canary_soak_rows()}
    canary = _row_text(rows[CANARY_TRAFFIC_RECORD])
    start = _row_text(rows[SOAK_START_RECORD])
    section = _section(INDEX.read_text(encoding="utf-8"), HISTORICAL_CANARY_SOAK_HEADING).lower()

    assert "fail_canary_catchup_rate_floor" in rows[CANARY_TRAFFIC_RECORD]["result"].lower()
    assert "2,000/2,000" in canary
    assert "zero failures" in canary
    assert "88.715123" in canary
    assert "1092/2000" in canary
    assert "546/2000" in canary
    assert "no verifier pass" in canary
    assert "observer" in canary
    assert "not started" in canary
    assert "latest attempt state" in canary or "latest attempt state" in section
    assert "preflight" in canary or "preflight" in section
    assert "does not claim" in canary
    assert "candidate" in canary
    assert "soak_running" in rows[SOAK_START_RECORD]["result"].lower()
    assert "not pass" in rows[SOAK_START_RECORD]["result"].lower()
    assert "golden-4h-soak-rv-20260807-01" in rows[SOAK_START_RECORD]["result"].lower()
    assert "1,440,000" in start
    assert "100" in start
    assert "dual_mean_90" in start
    assert "72k" in start
    assert "observer" in start
    assert "producer" in start
    assert "verifier" in start
    assert "rollback" in start
    assert "not started" in start
    assert "does not claim" in start
    assert "candidate" in start
    assert "current" in start
    assert "outcome" in start
    assert "soak-05" in start or "-05" in start
    assert "not a pass chain" in section
    for phrase in CANARY_FAILURE_UNCLAIMED_BOUNDARIES:
        assert phrase in canary
    for phrase in SOAK_START_UNCLAIMED_BOUNDARIES:
        assert phrase in start


def test_historical_capacity_blockers_section_precedes_current_outcomes() -> None:
    text = INDEX.read_text(encoding="utf-8")
    golden_at = text.index(ACCEPTANCE_HEADING)
    blockers_at = text.index(HISTORICAL_CAPACITY_BLOCKERS_HEADING)
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    canary_at = text.index(HISTORICAL_CANARY_SOAK_HEADING)

    assert golden_at < blockers_at < checkpoint_at < canary_at


def test_historical_capacity_blockers_index_lists_the_bounded_pair_once() -> None:
    indexed = _historical_capacity_blocker_record_paths()
    expected = (CHECKPOINT_BLOCKER_RECORD, RESOURCE_BLOCKER_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    assert indexed == list(expected)
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    for row in _historical_capacity_blocker_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_historical_capacity_blockers_expose_required_nonempty_fields() -> None:
    rows = _historical_capacity_blocker_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == HISTORICAL_CAPACITY_BLOCKER_DATES[identity]


def test_historical_capacity_blockers_supersession_is_reciprocal() -> None:
    blockers = {_identity_path(row["identity"]): row for row in _historical_capacity_blocker_rows()}
    checkpoint_blocker = blockers[CHECKPOINT_BLOCKER_RECORD]
    soak_resource_blocker = blockers[RESOURCE_BLOCKER_RECORD]
    checkpoint = {_identity_path(row["identity"]): row for row in _checkpoint_readiness_rows()}[
        CHECKPOINT_RECORD
    ]
    canary = {_identity_path(row["identity"]): row for row in _historical_canary_soak_rows()}[
        CANARY_TRAFFIC_RECORD
    ]

    assert checkpoint_blocker["supersedes"] == "None"
    assert soak_resource_blocker["supersedes"] == "None"
    assert [
        _resolve_index_link(target)
        for target in LINK_RE.findall(checkpoint_blocker["superseded by"])
    ] == [CHECKPOINT_RECORD]
    assert [
        _resolve_index_link(target)
        for target in LINK_RE.findall(soak_resource_blocker["superseded by"])
    ] == [CANARY_TRAFFIC_RECORD]
    assert [
        _resolve_index_link(target) for target in LINK_RE.findall(checkpoint["supersedes"])
    ] == [CHECKPOINT_BLOCKER_RECORD]
    assert [_resolve_index_link(target) for target in LINK_RE.findall(canary["supersedes"])] == [
        RESOURCE_BLOCKER_RECORD
    ]
    for row in (checkpoint_blocker, soak_resource_blocker):
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_historical_capacity_blockers_keep_published_digests() -> None:
    indexed = set(_historical_capacity_blocker_record_paths())

    assert indexed == set(HISTORICAL_CAPACITY_BLOCKER_DIGESTS)
    for relative, expected in HISTORICAL_CAPACITY_BLOCKER_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_historical_capacity_blocker_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _historical_capacity_blocker_rows()}
    checkpoint = _row_text(rows[CHECKPOINT_BLOCKER_RECORD])
    soak = _row_text(rows[RESOURCE_BLOCKER_RECORD])

    assert "unsafe_capacity" in rows[CHECKPOINT_BLOCKER_RECORD]["result"].lower()
    assert "blocked_before_mutation" in checkpoint
    assert "insufficient_non_protected_reclaim" in checkpoint
    assert "not accepted" in checkpoint
    assert "historical" in checkpoint
    assert "health evidence" in checkpoint
    assert "only for the restore/replay gate" in checkpoint
    assert "candidate" in checkpoint
    assert "blocked_resource_capacity" in rows[RESOURCE_BLOCKER_RECORD]["result"].lower()
    assert "not started" in soak
    assert "historical" in soak
    assert "preflight remains valid" in soak
    assert "health evidence" in soak
    assert "only as the latest attempt state" in soak
    assert "candidate" in soak
    for phrase in CHECKPOINT_BLOCKER_UNCLAIMED_BOUNDARIES:
        assert phrase in checkpoint
    for phrase in SOAK_RESOURCE_BLOCKER_UNCLAIMED_BOUNDARIES:
        assert phrase in soak


def test_current_freshness_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    security_at = text.index(SECURITY_DEPENDENCY_HEADING)
    freshness_at = text.index(CURRENT_FRESHNESS_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _current_freshness_record_paths()
    expected = (REAL_PATH_FRESHNESS_RECORD, DEMO_FRESHNESS_RECORD)
    rows = _current_freshness_rows()

    assert security_at < freshness_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CURRENT_FRESHNESS_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_current_freshness_records_are_complementary_not_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), CURRENT_FRESHNESS_HEADING).lower()
    rows = _current_freshness_rows()

    assert "complementary" in section
    assert "not a supersession chain" in section
    for row in rows:
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_current_freshness_records_keep_published_digests() -> None:
    indexed = set(_current_freshness_record_paths())

    assert indexed == set(CURRENT_FRESHNESS_DIGESTS)
    for relative, expected in CURRENT_FRESHNESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_current_freshness_claim_links_match_indexed_records() -> None:
    indexed = set(_current_freshness_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    latency = manifest["latency"]["real_path"]
    status_links = _status_record_links()

    assert indexed == {REAL_PATH_FRESHNESS_RECORD, DEMO_FRESHNESS_RECORD}
    assert REAL_PATH_FRESHNESS_RECORD in manifest["required_evidence"]
    assert latency["evidence"] == REAL_PATH_FRESHNESS_RECORD
    assert latency["p50_seconds"] == 3.02
    assert latency["p95_seconds"] == 5.70
    assert REAL_PATH_FRESHNESS_RECORD in status_links
    assert DEMO_FRESHNESS_RECORD in status_links
    assert manifest["production"]["status"] == "candidate"


def test_current_freshness_boundaries_keep_scopes_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _current_freshness_rows()}
    real_path = _row_text(rows[REAL_PATH_FRESHNESS_RECORD])
    demo = _row_text(rows[DEMO_FRESHNESS_RECORD])

    assert "s8" in rows[REAL_PATH_FRESHNESS_RECORD]["result"].lower()
    assert "3.02 s" in real_path
    assert "5.70 s" in real_path
    assert "n=20" in real_path
    assert "event_driven" in rows[DEMO_FRESHNESS_RECORD]["result"].lower()
    assert "1.06 s" in demo
    assert "1.99 s" in demo
    assert "n=30" in demo
    for phrase in REAL_PATH_FRESHNESS_BOUNDARIES:
        assert phrase in real_path
    for phrase in DEMO_FRESHNESS_BOUNDARIES:
        assert phrase in demo


def test_e4_replica_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    freshness_at = text.index(CURRENT_FRESHNESS_HEADING)
    e4_at = text.index(E4_REPLICA_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _e4_replica_record_paths()
    expected = (E4_TWO_POD_RECORD, E4_CHECK4_RECORD)
    rows = _e4_replica_rows()

    assert freshness_at < e4_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == E4_REPLICA_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_e4_replica_records_are_extension_not_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), E4_REPLICA_HEADING).lower()
    rows = _e4_replica_rows()

    assert "complementary extension" in section
    assert "not a supersession chain" in section
    assert "explicit a-to-b" in section
    assert "different kind snapshot" in section
    for row in rows:
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_e4_replica_records_keep_published_digests() -> None:
    indexed = set(_e4_replica_record_paths())

    assert indexed == set(E4_REPLICA_DIGESTS)
    for relative, expected in E4_REPLICA_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_e4_replica_claim_links_match_indexed_records() -> None:
    indexed = set(_e4_replica_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()

    assert indexed == {E4_TWO_POD_RECORD, E4_CHECK4_RECORD}
    assert E4_TWO_POD_RECORD in status_links
    assert E4_CHECK4_RECORD in status_links
    assert manifest["production"]["status"] == "candidate"


def test_e4_replica_boundaries_keep_topology_claims_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _e4_replica_rows()}
    two_pod = _row_text(rows[E4_TWO_POD_RECORD])
    check4 = _row_text(rows[E4_CHECK4_RECORD])

    assert "pass" in rows[E4_TWO_POD_RECORD]["result"].lower()
    assert "pass" in rows[E4_CHECK4_RECORD]["result"].lower()
    for phrase in E4_TWO_POD_BOUNDARIES:
        assert phrase in two_pod
    for phrase in E4_CHECK4_BOUNDARIES:
        assert phrase in check4


def test_historical_e4_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    current_e4_at = text.index(E4_REPLICA_HEADING)
    historical_e4_at = text.index(HISTORICAL_E4_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _historical_e4_record_paths()
    expected = (E4_REPLICA_TOPOLOGY_RECORD, E4_CHECK3_RECORD)
    rows = _historical_e4_rows()

    assert current_e4_at < historical_e4_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    assert E4_TWO_POD_RECORD not in indexed
    assert E4_CHECK4_RECORD not in indexed
    assert E4_REPLICA_TOPOLOGY_RECORD not in _e4_replica_record_paths()
    assert E4_CHECK3_RECORD not in _e4_replica_record_paths()
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == HISTORICAL_E4_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_historical_e4_records_are_extension_not_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), HISTORICAL_E4_HEADING).lower()
    rows = _historical_e4_rows()

    assert "historical" in section
    assert "intermediate" in section
    assert "extension" in section
    assert "not a supersession chain" in section
    assert "current status" in section
    assert "checks 1-2" in section
    assert "exactly-one delivery" in section or "exactly one delivery" in section
    assert "does not supersede" in section
    for row in rows:
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])
        resolved_supersedes = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["supersedes"])
        ]
        resolved_superseded_by = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["superseded by"])
        ]
        assert E4_TWO_POD_RECORD not in resolved_supersedes
        assert E4_CHECK4_RECORD not in resolved_supersedes
        assert E4_REPLICA_TOPOLOGY_RECORD not in resolved_supersedes
        assert E4_CHECK3_RECORD not in resolved_supersedes
        assert E4_TWO_POD_RECORD not in resolved_superseded_by
        assert E4_CHECK4_RECORD not in resolved_superseded_by
        assert E4_REPLICA_TOPOLOGY_RECORD not in resolved_superseded_by
        assert E4_CHECK3_RECORD not in resolved_superseded_by


def test_historical_e4_records_keep_published_digests() -> None:
    indexed = set(_historical_e4_record_paths())

    assert indexed == set(HISTORICAL_E4_DIGESTS)
    for relative, expected in HISTORICAL_E4_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in E4_REPLICA_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_historical_e4_claim_links_are_not_current_status_owners() -> None:
    indexed = set(_historical_e4_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()
    closure_links = _project_closure_record_links()
    required = manifest["required_evidence"]

    assert indexed == {E4_REPLICA_TOPOLOGY_RECORD, E4_CHECK3_RECORD}
    assert E4_REPLICA_TOPOLOGY_RECORD not in status_links
    assert E4_CHECK3_RECORD not in status_links
    assert E4_TWO_POD_RECORD in status_links
    assert E4_CHECK4_RECORD in status_links
    assert E4_REPLICA_TOPOLOGY_RECORD not in required
    assert E4_CHECK3_RECORD not in required
    assert E4_REPLICA_TOPOLOGY_RECORD not in closure_links
    assert E4_CHECK3_RECORD not in closure_links
    assert manifest["production"]["status"] == "candidate"


def test_historical_e4_boundaries_keep_intermediate_proofs_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _historical_e4_rows()}
    topology = _row_text(rows[E4_REPLICA_TOPOLOGY_RECORD])
    check3 = _row_text(rows[E4_CHECK3_RECORD])

    assert "pass" in rows[E4_REPLICA_TOPOLOGY_RECORD]["result"].lower()
    assert "pass" in rows[E4_CHECK3_RECORD]["result"].lower()
    assert "4a4709a0-0bdc-42bc-803a-2d49c1fb8f04" in topology
    assert "8 round-robin" in topology
    for phrase in E4_REPLICA_TOPOLOGY_BOUNDARIES:
        assert phrase in topology
    for phrase in E4_CHECK3_BOUNDARIES:
        assert phrase in check3


def test_current_endurance_scale_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    historical_e4_at = text.index(HISTORICAL_E4_HEADING)
    endurance_at = text.index(CURRENT_ENDURANCE_SCALE_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _current_endurance_scale_record_paths()
    expected = (S11_SOAK_RECORD, S13_SCALE_RECORD)
    rows = _current_endurance_scale_rows()

    assert historical_e4_at < endurance_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert RSS_REVERIFY_RECORD not in indexed
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CURRENT_ENDURANCE_SCALE_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_current_endurance_scale_records_are_complementary_with_scoped_api_rss() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), CURRENT_ENDURANCE_SCALE_HEADING).lower()
    indexed = _current_endurance_scale_record_paths()
    rows = {_identity_path(row["identity"]): row for row in _current_endurance_scale_rows()}
    s11 = rows[S11_SOAK_RECORD]
    s13 = rows[S13_SCALE_RECORD]
    s11_superseded_by_targets = LINK_RE.findall(s11["superseded by"])

    assert "complementary" in section
    assert "not a supersession chain" in section
    assert "scoped partial supersession" in section
    assert "api rss" in section
    assert "full-path endurance" in section
    assert "does not supersede" in section
    assert "rss-reverify-183-2026-07-11" in section
    assert RSS_REVERIFY_RECORD not in indexed
    assert s11["supersedes"] == "None"
    assert [_resolve_index_link(target) for target in s11_superseded_by_targets] == [
        RSS_REVERIFY_RECORD
    ]
    assert s11_superseded_by_targets[0].startswith("../perf/")
    assert s13["supersedes"] == "None"
    assert s13["superseded by"] == "None"
    _assert_supersession_cell(s11["supersedes"])
    _assert_supersession_cell(s11["superseded by"])
    _assert_supersession_cell(s13["supersedes"])
    _assert_supersession_cell(s13["superseded by"])
    s11_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(s11["supersedes"])]
    s11_superseded_by = [_resolve_index_link(target) for target in s11_superseded_by_targets]
    s13_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(s13["supersedes"])]
    s13_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(s13["superseded by"])
    ]
    assert S11_SOAK_RECORD not in s11_supersedes
    assert S13_SCALE_RECORD not in s11_supersedes
    assert RSS_REVERIFY_RECORD not in s11_supersedes
    assert S11_SOAK_RECORD not in s11_superseded_by
    assert S13_SCALE_RECORD not in s11_superseded_by
    assert S11_SOAK_RECORD not in s13_supersedes
    assert S13_SCALE_RECORD not in s13_supersedes
    assert RSS_REVERIFY_RECORD not in s13_supersedes
    assert S11_SOAK_RECORD not in s13_superseded_by
    assert S13_SCALE_RECORD not in s13_superseded_by
    assert RSS_REVERIFY_RECORD not in s13_superseded_by


def test_current_endurance_scale_records_keep_published_digests() -> None:
    indexed = set(_current_endurance_scale_record_paths())

    assert indexed == set(CURRENT_ENDURANCE_SCALE_DIGESTS)
    for relative, expected in CURRENT_ENDURANCE_SCALE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    assert (ROOT / RSS_REVERIFY_RECORD).is_file()


def test_current_endurance_scale_claim_links_match_status_rows() -> None:
    indexed = set(_current_endurance_scale_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()
    proven_rows = _status_table_rows("## Proven")
    known_issues = _section(STATUS.read_text(encoding="utf-8"), "## Known issues").lower()
    proven_by_path: dict[str, dict[str, str]] = {}
    proven_paths: set[str] = set()
    for row in proven_rows:
        for path in _status_cell_record_paths(row.get("evidence", "")):
            proven_paths.add(path)
            proven_by_path[path] = row

    assert indexed == {S11_SOAK_RECORD, S13_SCALE_RECORD}
    assert S11_SOAK_RECORD in status_links
    assert S13_SCALE_RECORD in status_links
    assert S11_SOAK_RECORD in proven_paths
    assert S13_SCALE_RECORD in proven_paths
    assert RSS_REVERIFY_RECORD not in proven_paths
    assert RSS_REVERIFY_RECORD in status_links
    assert "rss-reverify-183-2026-07-11.md" in known_issues
    assert proven_by_path[S11_SOAK_RECORD]["claim"] == S11_STATUS_CLAIM
    assert proven_by_path[S11_SOAK_RECORD]["result"] == S11_STATUS_RESULT
    assert proven_by_path[S13_SCALE_RECORD]["claim"] == S13_STATUS_CLAIM
    assert proven_by_path[S13_SCALE_RECORD]["result"] == S13_STATUS_RESULT
    assert manifest["production"]["status"] == "candidate"


def test_current_endurance_scale_boundaries_keep_scopes_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _current_endurance_scale_rows()}
    s11 = _row_text(rows[S11_SOAK_RECORD])
    s13 = _row_text(rows[S13_SCALE_RECORD])

    assert "s11" in rows[S11_SOAK_RECORD]["result"].lower()
    assert "s13" in rows[S13_SCALE_RECORD]["result"].lower()
    assert "does not supersede" in s11
    assert "full-path endurance" in s11
    for phrase in S11_SOAK_BOUNDARIES:
        assert phrase in s11
    for phrase in S13_SCALE_BOUNDARIES:
        assert phrase in s13


def test_current_s10_throughput_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    endurance_at = text.index(CURRENT_ENDURANCE_SCALE_HEADING)
    s10_at = text.index(CURRENT_S10_THROUGHPUT_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _current_s10_throughput_record_paths()
    expected = (S10_BURST_BASELINE_RECORD, S10_PACED_R4_RECORD)
    rows = _current_s10_throughput_rows()

    assert endurance_at < s10_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for relative in S10_INTERMEDIATE_RECORDS:
        assert relative not in indexed
    assert REAL_PATH_FRESHNESS_RECORD not in indexed
    assert SOAK_CAPACITY_RECORD not in indexed
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CURRENT_S10_THROUGHPUT_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_current_s10_throughput_records_are_not_a_direct_supersession_chain() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), CURRENT_S10_THROUGHPUT_HEADING)
    section_lower = section.lower()
    rows = {_identity_path(row["identity"]): row for row in _current_s10_throughput_rows()}
    baseline = rows[S10_BURST_BASELINE_RECORD]
    r4 = rows[S10_PACED_R4_RECORD]
    r4_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(r4["supersedes"])]
    r4_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(r4["superseded by"])
    ]

    assert any("not a direct supersession chain" in line for line in section.splitlines())
    assert "different modes" in section_lower
    assert "current four-hour paced-gate outcome" in section_lower
    assert "historical facts remain valid" in section_lower
    assert "already-closed serving-path gate" in section_lower
    assert "remains open" in section_lower
    assert baseline["supersedes"] == "None"
    assert baseline["superseded by"] == "None"
    assert r4_supersedes == [S10_PACED_R1_RECORD, S10_PACED_R3_RECORD]
    assert r4["supersedes"].count("[") == 2
    assert r4["superseded by"] == "None"
    assert S10_BURST_BASELINE_RECORD not in r4_supersedes
    assert S10_BURST_BASELINE_RECORD not in r4_superseded_by
    assert SOAK_CAPACITY_RECORD not in r4_supersedes
    assert SOAK_CAPACITY_RECORD not in r4_superseded_by
    _assert_supersession_cell(baseline["supersedes"])
    _assert_supersession_cell(baseline["superseded by"])
    _assert_supersession_cell(r4["supersedes"])
    _assert_supersession_cell(r4["superseded by"])


def test_current_s10_throughput_records_keep_published_digests() -> None:
    indexed = set(_current_s10_throughput_record_paths())

    assert indexed == set(CURRENT_S10_THROUGHPUT_DIGESTS)
    for relative, expected in CURRENT_S10_THROUGHPUT_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    assert (ROOT / S10_PACED_R1_RECORD).is_file()
    assert (ROOT / S10_PACED_R3_RECORD).is_file()
    f02_digest = hashlib.sha256((ROOT / SOAK_CAPACITY_RECORD).read_bytes()).hexdigest()
    assert f02_digest == F10_DIGESTS[SOAK_CAPACITY_RECORD]


def test_current_s10_throughput_claim_links_match_status_rows() -> None:
    indexed = set(_current_s10_throughput_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()
    proven_rows = _status_table_rows(S10_BASELINE_STATUS_HEADING)
    bridge_rows = _status_table_rows(S10_R4_STATUS_HEADING)
    proven_by_path: dict[str, dict[str, str]] = {}
    for row in proven_rows:
        for path in _status_cell_record_paths(row.get("evidence", "")):
            proven_by_path[path] = row
    bridge_by_path: dict[str, dict[str, str]] = {}
    for row in bridge_rows:
        for path in _status_cell_record_paths(row.get("state", "")):
            bridge_by_path[path] = row

    assert indexed == {S10_BURST_BASELINE_RECORD, S10_PACED_R4_RECORD}
    assert S10_BURST_BASELINE_RECORD in status_links
    assert S10_PACED_R4_RECORD in status_links
    assert S10_PACED_R1_RECORD not in status_links
    assert S10_PACED_R3_RECORD not in status_links
    assert proven_by_path[S10_BURST_BASELINE_RECORD]["claim"] == S10_BASELINE_STATUS_CLAIM
    assert proven_by_path[S10_BURST_BASELINE_RECORD]["result"] == S10_BASELINE_STATUS_RESULT
    assert S10_PACED_R4_RECORD not in proven_by_path
    assert bridge_by_path[S10_PACED_R4_RECORD]["step"] == S10_R4_STATUS_CLAIM
    assert bridge_by_path[S10_PACED_R4_RECORD]["bridge apply"] == S10_R4_STATUS_RESULT
    assert S10_BURST_BASELINE_RECORD not in bridge_by_path
    assert SOAK_CAPACITY_RECORD in status_links
    assert SOAK_CAPACITY_RECORD in _f10_record_paths()
    assert manifest["production"]["status"] == "candidate"
    assert manifest["production"]["full_soak_plus_rollback_after_traffic"] == (
        "BLOCKED_HOST_CAPACITY"
    )


def test_current_s10_throughput_boundaries_keep_scopes_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _current_s10_throughput_rows()}
    baseline = _row_text(rows[S10_BURST_BASELINE_RECORD])
    r4 = _row_text(rows[S10_PACED_R4_RECORD])

    assert "s10" in rows[S10_BURST_BASELINE_RECORD]["result"].lower()
    assert "pass" in rows[S10_PACED_R4_RECORD]["result"].lower()
    assert "consumed = applied = 1 440 000" in r4
    assert "produced = delivered = 1 440 000" in r4
    for phrase in S10_BURST_BASELINE_BOUNDARIES:
        assert phrase in baseline
    for phrase in S10_PACED_R4_BOUNDARIES:
        assert phrase in r4
