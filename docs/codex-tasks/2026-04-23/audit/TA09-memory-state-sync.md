# TA09 — Memory + state sync

**Priority:** P2 · **Estimate:** 30м

## Goal

Синхронизировать persistent memory (если CX имеет доступ — `~/.claude/projects/D--/memory/project_de_project.md` для Claude side) и state-файлы (`.workflow/logs/errors.jsonl`, `~/.claude/global-lessons.md` если cross-project) с реальностью после спринта CI repair.

## Context

- Memory note formate: см. `~/.claude/projects/D--/memory/MEMORY.md` index + `project_de_project.md` content
- Project log: `.workflow/logs/errors.jsonl` в репо — формат `{"ts","project","category","severity","actor","task","what","root_cause","fix","lesson"}`
- Global lessons: `~/.claude/global-lessons.md`, max 30 entries, durable cross-project lessons only
- **Если у CX нет доступа к Claude memory files** — сделать what's possible (`.workflow/logs/`) и в result.md явно отметить «memory sync deferred to Claude side, see TXX in Claude session»

## Deliverables

1. **`.workflow/logs/errors.jsonl`** — entry для значимых ошибок спринта CI repair:
   - Любая false-completion regression (если TA03 нашёл T00 regression)
   - Missed extras (test-integration cloud) — `{actor: "Claude", task: "T01 follow-up", what: "missed test-integration in ecc137c", root_cause: "manual workflow scan, not exhaustive grep", fix: "TA01 quick fix", lesson: "always grep ALL `pip install` lines before declaring follow-up done"}`
   - Любые другие выявленные incidents
   - Format строго JSONL (один JSON object per line, no commas between)

2. **`~/.claude/global-lessons.md`** (если accessible) — durable cross-project lesson:
   - Если такой урок есть из спринта (например, «pyiceberg в `[cloud]` extra влияет на 5+ test jobs — добавлять в каждый job не один `pip install`»)
   - Max 30 entries — старые superseded удалить first
   - Если lesson relevant only to DE_project — НЕ добавлять в global, только project log

3. **Memory snapshot** (`audit/TA09-result.md`):
   ```markdown
   ## Memory + state sync

   ### .workflow/logs/errors.jsonl additions
   <list of new entries with timestamps>

   ### ~/.claude/global-lessons.md changes
   - Added: <entries>
   - Removed (superseded): <entries>
   - No changes (no durable cross-project lesson found)

   ### project_de_project.md (Claude memory) recommendation
   <since CX likely cannot edit, summary of expected updates for next Claude session>
   ```

## Acceptance

- `audit/TA09-result.md` существует.
- `.workflow/logs/errors.jsonl` содержит as new lines все CI repair incidents (even if pre-existing — they're now documented).
- Если global-lessons.md был обновлён — diff показан в result.md.
- Recommendation для Claude memory side явный (даже если CX не может писать в `~/.claude/`).

## Notes

- НЕ добавлять trivial errors (опечатки, тесты пойманные сразу) в errors.jsonl. Только: rollback >5 мин, каскадное error, false-completion, abuse скилла.
- НЕ inflate global-lessons.md — если нет durable lesson, не добавлять filler.
- Если `.workflow/logs/` не существует — создать (per repo CLAUDE.md convention).
- Backstop: если CX не имеет write access к Claude memory — это ОК, в result.md явно отметить + предложить Claude session подхватить.
