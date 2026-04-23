# TA06 — Documentation alignment audit

**Priority:** P2 · **Estimate:** 1ч

## Goal

Проверить что документация (README, CHANGELOG, docs/) синхронна с current state репо после спринта CI repair. Catalog расхождений и предложить single doc-update PR.

## Context

- T00-T05 + T_AUDIT внесли значительные изменения: trivy ignore-unfixed, lighter docker-compose.e2e, key_id required, mypy override и т.д.
- Memory note: prior CHANGELOG `[Unreleased]` был обновлён в `5631353`, но T00-T05 после.

## Deliverables

Сравнить текущий код vs docs:

1. **README.md** в корне:
   - Версия (должна совпадать с `pyproject.toml` `version = "1.0.1"`)
   - Quick start commands — `pip install -e ".[dev]"` для разработки достаточно или нужно добавить `,cloud` etc.?
   - CI badge (если есть) — указывает на main? зелёный сейчас или red?
   - Architecture diagram / описание stack — актуально (Kafka KRaft, Flink 1.19, Iceberg+DuckDB)?
   - Links to docs/ — все живые?

2. **CHANGELOG.md** `[Unreleased]`:
   - T00 hardening упомянут?
   - T01 MCP+cloud extras?
   - T02 staging key_id fix?
   - T03 docker-compose.e2e.yml introduced?
   - T04 setuptools/wheel pin для CVE?
   - T05 audit recommendations?
   - Если что-то отсутствует — black box recommendation: "add CHANGELOG entry"

3. **docs/architecture/** (если существует):
   - Архитектурные diagrams не упоминают removed/renamed components?
   - SDK name collision (agentflow vs agentflow-sdk) — задокументирован как known issue?

4. **docs/deployment/** или `docs/runbook.md`:
   - E2E procedure упоминает `docker-compose.prod.yml` или новый `docker-compose.e2e.yml`?
   - Staging procedure упоминает `key_id` requirement?
   - Trivy/Security upgrade procedure (как добавлять `.trivyignore`)?

5. **docs/codex-tasks/2026-04-23/README.md** — index таблица:
   - T00-T05 + T_AUDIT — все статусы корректные (closed / in_progress)?
   - Order of execution — соответствует тому как сделалось (T00 → T01 → T02 → ... )?

6. **docs/codex-tasks/2026-04-24/README.md** — есть ли он?
   - Если нет, создать с T06-T09 индексом.

7. **`.github/PULL_REQUEST_TEMPLATE.md` / `CONTRIBUTING.md`** (если есть):
   - Coding standards упоминают ruff format?
   - Test running instructions актуальны (`pip install -e ".[dev,integrations,cloud]"` для full)?

Финальный `audit/TA06-result.md`:

```markdown
## Docs alignment audit

| Doc | Section | Issue | Recommendation |
```

И **single recommended PR**: `docs: align documentation with CI repair sprint state` — с конкретным diff (или хотя бы checklist of edits).

## Acceptance

- `audit/TA06-result.md` содержит matrix all relevant docs × all issues.
- Recommendation PR описан конкретно (не «обновить README» а «README.md строка 45-50: заменить 'docker-compose.prod.yml' на 'docker-compose.e2e.yml'»).
- Если CHANGELOG не имеет нужных entry — список конкретных bullet-ов для добавления.
- НЕ применять docs-PR в этом таске — только описание. TA10 consolidation возможно объединит с другими mini-PR.

## Notes

- НЕ переписывать архитектурные docs (если есть) — только flag что устарело. Real rewrite — отдельный ticket.
- README badges (CI, coverage) — если ссылаются на dead URL или wrong branch — flag, fix отдельным мини-PR.
- Если `docs/codex-tasks/2026-04-24/README.md` отсутствует — это явный gap, создать в этом таске (не считать quick fix limit нарушением).
- Backstop: если sections 3-4 (architecture / deployment) занимают весь час — flag только their existence + missing files; depth-review в follow-up.
