"""Audit F-07: the Windows shard runner must cover every collected test."""

from scripts.run_windows_unit_shards import group_files_into_shards, parse_executed_count


def _node_ids(spec: dict[str, int]) -> list[str]:
    return [f"{file}::test_{index}" for file, count in spec.items() for index in range(count)]


def test_shards_cover_every_file_exactly_once():
    node_ids = _node_ids({"tests/unit/a.py": 120, "tests/unit/b.py": 200, "tests/unit/c.py": 90})

    shards = group_files_into_shards(node_ids, shard_size=300)

    assigned = [file for files, _ in shards for file in files]
    assert sorted(assigned) == ["tests/unit/a.py", "tests/unit/b.py", "tests/unit/c.py"]
    assert len(assigned) == len(set(assigned))
    assert sum(count for _, count in shards) == len(node_ids)


def test_files_are_never_split_across_shards():
    node_ids = _node_ids({"tests/unit/big.py": 500, "tests/unit/small.py": 10})

    shards = group_files_into_shards(node_ids, shard_size=300)

    big_shards = [files for files, _ in shards if "tests/unit/big.py" in files]
    assert len(big_shards) == 1


def test_shard_size_bounds_multi_file_shards():
    node_ids = _node_ids({f"tests/unit/f{index}.py": 100 for index in range(9)})

    shards = group_files_into_shards(node_ids, shard_size=300)

    assert len(shards) == 3
    assert all(count <= 300 for _, count in shards)


def test_parse_executed_count_reads_the_summary_line():
    output = "\n".join(
        [
            "............",
            "=== 12 passed, 3 skipped, 1 xfailed, 2 warnings in 4.56s ===",
        ]
    )

    assert parse_executed_count(output) == 16


def test_parse_executed_count_counts_failures_and_errors():
    output = "=== 2 failed, 40 passed, 1 error in 9.99s ==="

    assert parse_executed_count(output) == 43


def test_parse_executed_count_ignores_warning_only_lines():
    assert parse_executed_count("=== 2 warnings in 1.00s ===\nno summary") == 0
