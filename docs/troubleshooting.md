# Troubleshooting

Find the first failing boundary here, then follow its owner: the
[operational runbook](runbook.md) for exact procedures, the
[quickstart](quickstart.md) for the smallest local path, the
[deployment walkthrough](deployment.md) for environment choices, the
[full API reference](api-reference.md) for request and authentication
contracts, or the [contributor guide](contributing.md) for change validation.

## Triage by symptom

| Symptom | Narrow first | Procedure owner |
| --- | --- | --- |
| The first local run fails | Setup, preparation, or API boot | [Quickstart](quickstart.md) |
| An optional service stack does not settle | Prerequisite or service health | [Deployment walkthrough](deployment.md), then [runbook](runbook.md) |
| The API is unavailable or its address is occupied | Missing process, unhealthy process, or address conflict | [API incident procedure](runbook.md#api-does-not-respond) |
| Event flow is slow or stopped | Source, transport, processing, or store | [Incident response](runbook.md#incident-response) |
| Local data is missing or unexpected | Selected profile, preparation step, or concurrent writer | [Local pipeline operations](runbook.md#local-pipeline-operations) |
| A request is rejected | Authentication, authorization, or request contract | [Full API reference](api-reference.md) |

## Narrow the boundary

1. Reproduce the smallest applicable quickstart path.
2. Classify the failure as environment, request path, or event path.
3. Record the first failed boundary, then follow its owner.
4. Do not reset local state unless the procedure requires it.

## Choose the verification owner

| Change or incident | Verification owner |
| --- | --- |
| Documentation, runtime, backend, or client change | [Contributor guide](contributing.md) |
| Incident response or recurring maintenance | [Operational runbook](runbook.md) |
| Current acceptance or external gate | [Engineering status](STATUS.md) |

When escalating, include the selected profile, first error, expected and actual
results, and the latest relevant change. Exclude credentials and private data.
