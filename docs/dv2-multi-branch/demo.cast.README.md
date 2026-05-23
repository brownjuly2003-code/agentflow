# demo.cast — terminal recording of the live 2-minute pitch

`demo.cast` is an [asciinema](https://asciinema.org/) v2 recording of
`bash demo_runner.sh` executed against the `hq-demo` cluster. Captured
on 2026-05-23 at 130×35 with `xterm-256color`. Total runtime ~42 s
(silent — no voice-over, faster than the 2:00 pitch budget).

Use it as one of three things:

1. **Standalone "watch the cluster" demo** — short visual artifact that
   shows every beat producing real output, no narration needed.
2. **Base track for voice-over** — play at 0.5× (`asciinema play --speed
   0.5 demo.cast`) and record audio over the top. Total becomes ~84 s,
   close to the 2:00 pitch budget.
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

The ANSI-stripped transcript is in `demo_transcript.txt` for diff-friendly
review (what the cast captures, line for line).

## What's recorded

The 6 beats from [`pitch.md`](./pitch.md) executed end-to-end against
the running cluster:

| Beat | Command | Live output |
|------|---------|-------------|
| 1 | `kubectl get nodes --show-labels` | 3 nodes with `branch=msk` / `nodepool` / `workload` labels |
| 2 | CH: count tables in `rv` by prefix | bv=6, hub=8, lnk=8, sat=39 |
| 3 | CH: `record_source` distribution from `hub_order` | msk 40.5% / spb 24.1% / ekb 14.5% / dxb 11.2% / ala 9.7% |
| 4 | CH: BV MDM PII + loyalty per branch | msk 800/800/640, dxb 200/200/0 |
| 5a | `kubectl create job --from=cronjob/dv2-cold-offload-msk` | job created, succeeds in ~8 s |
| 5b | `mc ls -r local/cold-tier` | parquet files in MinIO for all 5 branches |

The recording was made on hq-demo at the state reflected in
[`SESSION_HANDOFF.md`](./SESSION_HANDOFF.md) § Current cluster state.

## Regenerating

```bash
# On the iMac (asciinema already installed at ~/Library/Python/3.9/bin/asciinema)
scp docs/dv2-multi-branch/demo_runner.sh julia@192.168.1.133:/tmp/
ssh julia@192.168.1.133 \
  'export PATH=$HOME/Library/Python/3.9/bin:$HOME/lima/bin:$HOME/bin:$PATH && \
   TERM=xterm-256color asciinema rec --cols 130 --rows 35 \
     -t "DV2.0 multi-branch live demo" \
     -c "bash /tmp/demo_runner.sh" /tmp/demo.cast'
scp julia@192.168.1.133:/tmp/demo.cast docs/dv2-multi-branch/demo.cast
```

After regeneration: `kubectl delete job -n dv2 $(kubectl get jobs -n dv2 -o name | grep cold-demo)`
to clean up the test job created by Beat 5a.
