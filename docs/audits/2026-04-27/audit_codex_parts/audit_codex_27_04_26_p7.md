# SDK TypeScript Audit - 2026-04-27

Baseline before audit:
- HEAD: `4a13d36`
- `sdk-ts/dist`: 14 files, 31,528 bytes
- `sdk-ts/package.json` public export subpaths: 1 (`"."`)
- `sdk-ts` tracked files: 14; local file count was 957 because ignored `node_modules/` and `dist/` are present

## SDK-specific findings

### High - `npm test` is polluted by ignored mutation output and misses real SDK-local tests

Evidence:
- `sdk-ts/package.json:25` runs `vitest run --root .. tests/client.test.ts`.
- `.gitignore:61` ignores `mutants/`, but Vitest still discovers tests there when the path filter matches.
- `cd sdk-ts && npm test` ran 2 files: `tests/client.test.ts` (26 tests) and `mutants/tests/client.test.ts` (15 tests), 41 tests total.
- The intended SDK-local tests under `sdk-ts/tests/` are not part of `npm test`. Running them directly passed 16 tests across:
  - `sdk-ts/tests/retry.test.ts`
  - `sdk-ts/tests/circuitBreaker.test.ts`
  - `sdk-ts/tests/resilience-integration.test.ts`

Impact:
- The advertised SDK test command is not deterministic when mutation output exists locally.
- It can pass with stale generated tests and still skip the newer `sdk-ts/tests` coverage.
- `mutants/tests/client.test.ts` is a stale subset of `tests/client.test.ts`; `git diff --no-index --stat` shows 179 deleted lines versus the canonical test file, including the retry/circuit/resilience block.

Recommended fix:
- Treat `mutants/tests/client.test.ts` as generated mutation-output pollution, not as a source test.
- Delete or clean `mutants/` before SDK test runs.
- Update the SDK test script to exclude mutation output and include the SDK-local tests. Verified command:

```bash
vitest run --root .. tests/client.test.ts sdk-ts/tests/retry.test.ts sdk-ts/tests/circuitBreaker.test.ts sdk-ts/tests/resilience-integration.test.ts --exclude mutants/**
```

Verification for that command: 4 files passed, 42 tests passed.

### Medium - npm publish workflow builds but does not run SDK tests

Evidence:
- `.github/workflows/publish-npm.yml:63-90` installs dependencies, runs `npm run build`, runs `npm publish --dry-run`, then publishes on production tags.
- There is no `npm test` step in the publish path.

Impact:
- A release tag can publish a TypeScript SDK artifact even if the SDK test command is polluted, broken, or skipping `sdk-ts/tests`.

Recommended fix:
- After fixing `sdk-ts/package.json:test`, add `npm test` to `publish-npm.yml` between build and dry-run publish.
- `npm run build` already typechecks through `tsc -p tsconfig.json`; a separate `npm run typecheck` is optional duplication unless the project wants an explicit gate.

### Low / compatibility note - package is root-only ESM; CommonJS Node 18 is not guaranteed

Evidence:
- `sdk-ts/package.json:5-13` sets `"type": "module"` and exports only `"import"` plus `"types"` for `"."`.
- There is no `"require"` or `"default"` condition.
- Node `v22.20.0` passed both `import('@agentflow/client')` and `require('.')`, but that is Node 22 behavior.
- Attempted Node 18 check via `npx -p node@18` failed due registry `ECONNRESET`, so Node 18 CommonJS behavior was not freshly verified in this audit.

Impact:
- Browser bundlers and ESM Node consumers are covered.
- CommonJS consumers on older Node 18 runtimes may fail unless the package intentionally declares ESM-only support.

Recommended decision:
- If ESM-only is intentional, document it in `sdk-ts/README.md`.
- If CommonJS support is required, add a CJS build and a `"require"` export condition.

## Dist, exports, and runtime compatibility checks

Passed:
- `cd sdk-ts && npm run typecheck` passed.
- `cd sdk-ts && npm run build` passed.
- `cd sdk-ts && npm pack --dry-run --json` produced `agentflow-client-1.1.0.tgz`, 16 files, package size 8,163 bytes, unpacked size 32,883 bytes.
- `cd sdk-ts && npm publish --dry-run --access public` passed dry-run and showed only `README.md`, `package.json`, and `dist/**` in the tarball.
- `node -e "import('./dist/index.js')..."` imported the built dist and executed `client.health()` successfully.
- `node --input-type=module -e "import { AgentFlowClient, RetryPolicy } from '@agentflow/client'..."` resolved the package self-reference successfully.
- esbuild browser bundle check passed: `browser-bundle-ok`.
- esbuild node bundle check passed: `node-bundle-ok`.
- Static scan found no Node builtin imports such as `node:`, `fs`, `path`, `http`, `https`, `stream`, `crypto`, `Buffer`, or `require(` in `sdk-ts/src` or `sdk-ts/dist`.

Notes:
- `git check-ignore -v` confirms `sdk-ts/dist`, `sdk-ts/node_modules`, and `mutants/` are ignored.
- `npm pack --dry-run` confirms ignored local `node_modules/` and `mutants/` do not enter the npm tarball.
- `dist` is not tracked, so clean publish depends on the workflow build step. The current npm workflow does build before publish.

## Decision on `mutants/tests/client.test.ts`

Decision: remove/quarantine it as disposable mutation output. Do not promote it, do not copy assertions from it, and do not count it as SDK test coverage.

Reason:
- It is under ignored `mutants/`.
- It is stale relative to `tests/client.test.ts`.
- It is currently being picked up accidentally by `sdk-ts`'s `npm test`.
- The canonical coverage should be `tests/client.test.ts` plus `sdk-ts/tests/*.test.ts`, with `mutants/**` excluded from Vitest.
