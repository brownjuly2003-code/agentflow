from scripts import benchmark_throughput_realpath


def test_exact_catchup_completion_rejects_ninety_nine_percent() -> None:
    assert not benchmark_throughput_realpath.catchup_is_complete(
        processed=99.0,
        produced=100,
        lag=0.0,
        baseline_lag=0.0,
        pending_latency_count=0,
        completion_ratio=1.0,
    )
    assert benchmark_throughput_realpath.catchup_is_complete(
        processed=100.0,
        produced=100,
        lag=0.0,
        baseline_lag=0.0,
        pending_latency_count=0,
        completion_ratio=1.0,
    )
