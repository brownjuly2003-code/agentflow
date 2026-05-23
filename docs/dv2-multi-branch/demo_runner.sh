#!/usr/bin/env bash
# Scripted execution of the 6 beats from pitch.md for asciinema recording.
# Designed for silent terminal capture (no voice-over) — the resulting cast
# is a base track over which voice can be overlaid in post, or used as a
# standalone "watch the cluster" artifact.
#
# Run on the iMac demo host with asciinema:
#   asciinema rec -t "DV2.0 multi-branch live demo" -c \
#     "bash demo_runner.sh" demo.cast
#
# Total runtime ~115-125s (matches pitch.md 2:00 budget).

set -euo pipefail
export PATH="$HOME/lima/bin:$HOME/bin:$PATH"

# Prompt helpers (visible in cast)
PROMPT="\033[1;36m$\033[0m"
HEADER="\033[1;33m"
RESET="\033[0m"

beat() {
    echo
    echo -e "${HEADER}# === $1 ===${RESET}"
    sleep 1.5
}

run() {
    echo -e "${PROMPT} $*"
    sleep 0.8
    eval "$@"
    sleep 2.5
}

# 00:00 hook — no command
beat "Beat 1 — Cluster topology (00:25)"
run "kubectl get nodes --show-labels | head -5"

beat "Beat 2 — DV2.0 model surface (00:45)"
run "kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo --query \"SELECT splitByString('_', name)[1] AS kind, count() FROM system.tables WHERE database='rv' GROUP BY kind ORDER BY kind\""

beat "Beat 3 — Multi-branch distribution (01:05)"
run "kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo --query \"SELECT splitByString('__', record_source)[2] AS branch, count() AS orders, round(count()*100.0/(SELECT count() FROM rv.hub_order),1) AS pct FROM rv.hub_order GROUP BY branch ORDER BY pct DESC FORMAT PrettyCompact\""

beat "Beat 4 — Business Vault MDM (01:25)"
run "kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo --multiline --query \"SELECT 'msk' AS branch, count() AS rows, countIf(first_name != '') AS with_pii, countIf(loyalty_segment != '') AS with_loyalty FROM rv.bv_customer_mdm__msk UNION ALL SELECT 'dxb', count(), countIf(first_name != ''), countIf(loyalty_segment IS NOT NULL AND loyalty_segment != '') FROM rv.bv_customer_mdm__dxb FORMAT PrettyCompact\""

beat "Beat 5a — Cold offload (01:50)"
run "kubectl create job --from=cronjob/dv2-cold-offload-msk cold-demo-$RANDOM -n dv2"
sleep 8

beat "Beat 5b — MinIO parquet listing"
run "kubectl exec -n dv2 minio-0 -- mc ls -r local/cold-tier | tail -5"

beat "Closing (02:00) — Single bootstrap reproduces everything"
echo -e "${PROMPT} bash infrastructure/dv2/bootstrap.sh"
sleep 2

echo
echo -e "${HEADER}Demo complete. See docs/dv2-multi-branch/demo_evidence.md for the full breakdown.${RESET}"
sleep 2
