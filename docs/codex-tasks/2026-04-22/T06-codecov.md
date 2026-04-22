# T06 — Codecov coverage publishing

**Priority:** P2 · **Estimate:** 1ч

## Goal

Опубликовать процент code coverage в README через Codecov badge.

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- `pytest-cov` уже в dev dependencies
- CI генерирует `coverage.xml` (видно по факту в корне репо)
- README заявляет «543 tests» без coverage %
- Codecov token нужно будет добавить юзеру вручную в GitHub secrets — workflow должен толерировать его отсутствие

## Deliverables

1. **Обновить** `.github/workflows/ci.yml`:
   - После шага `pytest --cov=src --cov-report=xml` (проверить точную команду — может быть через `make test-cov`) добавить:
     ```yaml
     - name: Upload coverage to Codecov
       uses: codecov/codecov-action@v4
       with:
         token: ${{ secrets.CODECOV_TOKEN }}
         files: ./coverage.xml
         fail_ci_if_error: false
         verbose: true
     ```

2. **README.md** — добавить badge в существующий блок badges:
   ```markdown
   [![codecov](https://codecov.io/gh/<OWNER>/<REPO>/branch/main/graph/badge.svg)](https://codecov.io/gh/<OWNER>/<REPO>)
   ```
   (OWNER/REPO определить по существующим badges в README — использовать тот же паттерн)

3. **`codecov.yml`** в корне:
   ```yaml
   coverage:
     status:
       project:
         default:
           target: auto
           threshold: 2%
       patch:
         default:
           target: 80%
           threshold: 0%

   comment:
     layout: "reach, diff, flags, files"
     behavior: default
     require_changes: true

   ignore:
     - "tests/**/*"
     - "scripts/**/*"
     - "examples/**/*"
   ```

4. **`docs/operations/codecov-setup.md`** — краткая инструкция:
   - Зайти на codecov.io, sign in через GitHub
   - Добавить репо
   - Скопировать upload token, вставить в GitHub Settings → Secrets → `CODECOV_TOKEN`
   - Merge этот PR → badge активируется после первого CI run

5. Один коммит `ci: publish coverage reports to Codecov`

## Acceptance

- После merge и CI run — badge в README показывает актуальный %
- CI **не падает** если `CODECOV_TOKEN` отсутствует (`fail_ci_if_error: false`)
- `codecov.yml` валидный: `curl --data-binary @codecov.yml https://codecov.io/validate` → `Valid!`
- `docs/operations/codecov-setup.md` самодостаточен для юзера

## Notes

- Если юзер ещё не заводил Codecov — workflow будет работать в noop до появления токена, это ожидаемо
- Не писать hard-coded OWNER/REPO в badge URL если в README уже используется переменный паттерн — следовать существующей конвенции
- Если в проекте политика «coverage only from main» — убрать `patch.default` target, оставить только `project.default`
