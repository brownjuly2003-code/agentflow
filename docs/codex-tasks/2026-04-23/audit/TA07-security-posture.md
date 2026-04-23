# TA07 — Security posture review

**Priority:** P1 · **Estimate:** 1-2ч

## Goal

Зафиксировать current security findings (Trivy, Bandit, Safety) на HEAD, проверить что T04 setuptools/wheel pin адекватен, audit `.trivyignore` (если он появился).

## Context

- T00 hardening добавил `ignore-unfixed: true` в Trivy — теперь gate срабатывает только на actionable HIGH/CRITICAL CVE с fix-version
- T04 (`044543e`) запинил `setuptools==82.0.1 wheel==0.47.0` в prod image — починил конкретные CVE
- Security workflow на 739ceb4 — ✅ зелёный, но это значит `ignore-unfixed` достаточен, не значит что у нас 0 vulns
- Bandit baseline: `.bandit-baseline.json` в корне; CI запускает `python scripts/bandit_diff.py` против него
- Safety: `.tmp-security/requirements-{main,sdk}.txt` собираются in-job из `pyproject.toml` deps + `requirements.txt`

## Deliverables

1. **Trivy current scan**:
   ```bash
   docker compose -f docker-compose.prod.yml build agentflow-api
   IMAGE=agentflow_de_project-agentflow-api:latest  # или название после build
   trivy image --severity HIGH,CRITICAL --format table $IMAGE > audit-trivy-all.txt
   trivy image --severity HIGH,CRITICAL --ignore-unfixed --format table $IMAGE > audit-trivy-actionable.txt
   ```
   - Все findings → `audit-trivy-all.txt`
   - Actionable (с fix) → `audit-trivy-actionable.txt`
   - Если actionable не пустой → CI должен быть red, но он green → проверить почему. Возможно severity mismatch (Trivy DB vs ours).

2. **Bandit current findings**:
   ```bash
   bandit -r src sdk --ini .bandit --severity-level medium -f json -o /tmp/bandit-now.json
   python scripts/bandit_diff.py .bandit-baseline.json /tmp/bandit-now.json > audit-bandit-diff.txt
   ```
   - Если diff не пустой → review case-by-case

3. **Safety current findings**:
   ```bash
   mkdir -p .tmp-security
   python -c "<repeat the script from security.yml job>"  # gen requirements-main/sdk.txt
   safety check -r .tmp-security/requirements-main.txt -r .tmp-security/requirements-sdk.txt > audit-safety.txt
   ```

4. **`.trivyignore` audit** (если файл появился):
   ```bash
   test -f .trivyignore && cat .trivyignore
   ```
   - Каждая запись имеет comment с обоснованием (`# CVE-XXXX: <pkg> <ver> — fix requires <event>, target <date>`)?
   - Есть запись без обоснования → flag for ticket
   - Запись о CVE которая теперь fixed upstream → recommend remove

Финальный `audit/TA07-result.md`:

```markdown
## Security posture (HEAD <sha>, scan date <YYYY-MM-DD>)

### Trivy
- Total HIGH/CRITICAL: <N>
- Actionable (with fix): <M>
- Unfixed (ignored by ignore-unfixed): <K>

| Severity | CVE | Package | Version | Fix-version | Status (action) |
| ... |

### Bandit diff vs baseline
| File:Line | Severity | Issue | Recommendation |

### Safety
| Package | Vulnerability | Affected | Fixed-in | Action |

### .trivyignore audit
| CVE | Comment | Justification valid? | Action |
```

Action для каждого finding — `bump <pkg> to <ver>` / `add to .trivyignore with reason X` / `accept for now (re-review <date>)` / `false positive (suppress with link to upstream issue)`.

## Acceptance

- `audit/TA07-result.md` содержит все 4 секции.
- Если Trivy актуально-actionable не пустой и CI зелёный — root cause расследован (rare config edge case или Trivy DB hang между scans).
- Каждый action имеет конкретный proposal (commit message draft).
- НЕ применять fixes/upgrades в этом таске — только catalog. TA10 consolidation возможно объединит security PR.

## Notes

- НЕ ставить severity на MEDIUM или LOW — мы только HIGH/CRITICAL gate-им; lower noise.
- Если Bandit diff поднимает findings которые pre-T00 не было — возможна regression, P0 priority в action.
- Safety может поднимать transitive deps которых нет в pyproject — отметить, но не fix-ить (transitive обычно из dev tools).
- Trivy DB обновляется ежедневно — scan на одной machine vs CI runner может расходиться. Если расхождение — отметить с timestamp.
- Backstop: если Docker недоступен и Trivy scan невозможен — выполнить только Bandit + Safety, отметить Trivy `not run — no docker available, see GitHub Security tab`.
