# demo.cast — terminal recording of the live 2-minute pitch

> **Re-recorded 2026-07-06** on the Mac `hq-demo` kind stand, against the
> live cluster on the current kitchen-appliance-importer legend. `demo.cast`,
> `demo_transcript.txt` and `demo_voiced.mp4` all now show the current
> five-branch split and real row counts — the 2026-05-23 fashion-retailer
> capture (old 40/25/15/10/10 split) is fully retired. The prior version is
> preserved in git history if needed for comparison.

`demo.cast` is an [asciinema](https://asciinema.org/) v2 recording of
`bash demo_runner.sh` executed against the `hq-demo` cluster. Captured
on 2026-07-06 at 130×35 with `xterm-256color`. Total runtime ~54 s
(silent — no voice-over, faster than the 2:00 pitch budget).

Use it as one of three things:

1. **Standalone "watch the cluster" demo** — short visual artifact that
   shows every beat producing real output, no narration needed.
2. **Base track for voice-over** — already built. See
   [`demo_voiced.mp4`](./demo_voiced.mp4) (~118 s, h264 + AAC, 3.4 MB):
   cast slowed to match a Russian TTS narration of the demo.
   Reproducible via [`demo_voiced.build.sh`](./demo_voiced.build.sh)
   from [`demo_voiced.narration.txt`](./demo_voiced.narration.txt).
   Web-UI counterpart: [`demo_webui.mp4`](./demo_webui.mp4) (~60 s,
   1.6 MB) — Playwright run through Argo workflow archive + DAG and
   the MinIO `cold-tier` bucket browser, same TTS pipeline. Build
   script: [`demo_webui.capture.py`](./demo_webui.capture.py).
   **Not re-recorded in the 2026-07-06 pass**: its narration text was
   already legend-clean, and re-capturing it would need a live Argo
   Workflows UI, which was not installed on the Mac stand this session
   (see `demo_evidence.md` §12 for why — the same concurrency risk that
   OOM'd the shared host once already). Treat it as unchanged/out of
   scope until Argo Workflows is actually stood up.
   Mart-layer counterpart: [`demo_dbt_docs.mp4`](./demo_dbt_docs.mp4)
   (~55 s, 1.7 MB) — Playwright walk-through of the auto-generated
   dbt docs site (Project tree → `customer_360` → `branch_pnl` →
   `returns_velocity`, including the rv → mart lineage graph). Build
   script: [`demo_dbt_docs.capture.py`](./demo_dbt_docs.capture.py);
   companion Pod manifest:
   [`../../infrastructure/dv2/dbt/dbt-docs-pod.yaml`](../../infrastructure/dv2/dbt/dbt-docs-pod.yaml).
   Also not touched this session (out of scope for the B2-mp4 item).
3. **Re-render to GIF/MP4** for embedding in a portfolio page —
   [`agg`](https://github.com/asciinema/agg) for GIF,
   [`svg-term-cli`](https://github.com/marionebl/svg-term-cli) for SVG,
   or upload to asciinema.org for hosted playback.

## Quick view options

```bash
# Local playback (Python pip install asciinema)
asciinema play docs/dv2-multi-branch/demo.cast

# Plain text (renders ANSI as colors only if terminal supports it)
asciinema cat docs/dv2-multi-branch/demo.cast

# Upload anonymously to asciinema.org (returns a shareable URL)
asciinema upload docs/dv2-multi-branch/demo.cast
```

### Browser embed

`demo.html` in this directory is a self-contained page that loads
`demo.cast` via [asciinema-player](https://docs.asciinema.org/manual/player/)
from a CDN. Open it directly in any browser, or host the directory
anywhere static (GitHub Pages / Vercel / S3).

### Hosted

The 2026-05-23 cast was uploaded anonymously to asciinema.org
(`https://asciinema.org/a/ZBTnOWGs5Jzhn7rW`, 7-day TTL — long since expired).
The 2026-07-06 re-recording has not been re-uploaded; `asciinema upload
docs/dv2-multi-branch/demo.cast` (see "Quick view options" above) produces a
fresh shareable URL when needed.

The ANSI-stripped transcript is in `demo_transcript.txt` for diff-friendly
review (what the cast captures, line for line).

## What's recorded

The 6 demo beats executed end-to-end against
the running cluster (2026-07-06 capture, current kitchen-appliance-importer
legend):

| Beat | Command | Live output |
|------|---------|-------------|
| 1 | `kubectl get nodes --show-labels` | 3 nodes with `branch=msk` / `nodepool` / `workload` labels |
| 2 | CH: count tables in `rv` by prefix | bv=6, hub=8, lnk=8, sat=48 |
| 3 | CH: `record_source` distribution from `hub_order`, collapsed to branch | msk 94.7% / spb 1.8% / dxb 1.5% / ekb 1.3% / ala 0.7% |
| 4 | CH: BV MDM PII + loyalty per branch | msk 2240/2240/152, dxb 80/80/0 |
| 5a | `kubectl create job --from=cronjob/dv2-cold-offload-msk` | job created, succeeds |
| 5b | `mc ls -r local/cold-tier` | parquet files in MinIO for all 5 branches |

All 6 beats now reflect the current kitchen-appliance-importer legend,
including the §10 hot-tier OLTP bridge rows folded into msk/dxb (matching
`demo_evidence.md` §4/§5/§8/§10, all re-captured 2026-07-06 on the same live
`hq-demo` kind stand this cast was recorded against).

The recording was made on the `hq-demo` cluster in the multi-branch state
described by the DV2 docs in this directory.

## Regenerating

```bash
# On the iMac (asciinema already installed at ~/Library/Python/3.9/bin/asciinema)
scp docs/dv2-multi-branch/demo_runner.sh <user>@<mac-host>:/tmp/
ssh <user>@<mac-host> \
  'export PATH=$HOME/Library/Python/3.9/bin:$HOME/lima/bin:$HOME/bin:$PATH && \
   TERM=xterm-256color asciinema rec --cols 130 --rows 35 \
     -t "DV2.0 multi-branch live demo" \
     -c "bash /tmp/demo_runner.sh" /tmp/demo.cast'
scp <user>@<mac-host>:/tmp/demo.cast docs/dv2-multi-branch/demo.cast
```

After regeneration: `kubectl delete job -n dv2 $(kubectl get jobs -n dv2 -o name | grep cold-demo)`
to clean up the test job created by Beat 5a.

**Gotcha (2026-07-06):** Beat 5b's `mc ls -r local/cold-tier` needs an `mc`
alias named `local` configured *inside the `minio-0` pod itself* — the
bucket-init Job configures its own alias in its own short-lived container,
which does not persist into `minio-0`. If the cold-tier was populated via
ClickHouse's native `s3()` function directly (as this session's re-capture
did — see `demo_evidence.md` §9) rather than via the CronJobs' own `mc`
calls, run this once before recording:
`kubectl exec -n dv2 minio-0 -- mc alias set local http://localhost:9000 <user> <password>`
(credentials in the `minio-creds` Secret) — otherwise Beat 5b fails with
`mc: <ERROR> Unable to list folder. Access Denied.`
