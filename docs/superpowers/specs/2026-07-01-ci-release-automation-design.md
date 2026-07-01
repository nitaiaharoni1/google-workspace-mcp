# CI, release automation, and the FakeAPI drift guard: design

**Date:** 2026-07-01
**Status:** Draft, pending review
**Author:** nitai (+ Claude)

## Problem

This package asks users to hand it Gmail and Drive scopes, yet the repo has no
CI at all: no `.github/` directory, no workflow files, no badge. `pytest` is
the documented gate, but nothing runs it on push, so a broken commit on `main`
is only discovered at the next local run. Releases are manual (local
`python -m build` plus a Keychain-held PyPI token), which is slow and
error-prone. And the test fakes can silently drift from the real API wrappers:
commit `2851b82` hand-fixed exactly this (Gmail's `FakeAPI` missing the new
`html`/`cc` parameters), and the calendar/sheets/docs/drive server tests use
bare `MagicMock`, which accepts *any* call signature, so drift there produces
green tests and broken runtime behavior.

## Goals

1. Every push and PR to `main` runs the full non-live suite on Python
   3.10 through 3.13, green within ~5 minutes, no secrets required.
2. Tag-to-PyPI: pushing a `v*` tag builds and publishes
   `google-workspace-suite-mcp` via PyPI Trusted Publishing, with no token
   handling, in under 5 minutes.
3. Fake/wrapper signature drift is caught at PR time by a dedicated test, not
   by a human noticing a runtime TypeError.
4. A CI badge on the README once the repo is public (credibility for a
   package that requests restricted scopes).

## Non-goals

- **No coverage gates or coverage reporting.** The suite is the spec; a
  percentage target adds ceremony without catching more bugs at this size.
- **No type checking (mypy/pyright) in this pass.** The codebase is untyped in
  places and the payoff is separate from CI bring-up. P2, revisit later.
- **Live tests never run in CI.** They hit real Google APIs with a real
  account. CI must provably exclude them (see Testing).
- **No repo-visibility change in this spec.** The repo is currently private on
  GitHub; making it public is a product decision tracked as an open question.

## Current state (verified)

- No `.github/` directory or CI config anywhere in the repo.
- Remote exists: `git@github.com:nitaiaharoni1/google-workspace-mcp.git`,
  currently **private**. GitHub Actions works on private repos (free-plan
  minute quota applies); the badge only has public value later.
- `pyproject.toml`: version `0.3.1`, `setuptools>=77` backend,
  `requires-python >= 3.10`, dev extras are `pytest`, `pytest-anyio`, `anyio`.
  Classifiers list 3.10, 3.11, 3.12 (no 3.13 classifier yet).
- Runtime deps install from PyPI, including the sibling packages
  `google-auth-core`, `gmail-cli-oauth`, `google-calendar-cli`. CI therefore
  tests against the *released* sibling contract, which is exactly what users
  install. (Corollary: when a server starts relying on a new sibling feature,
  the floor pin must be bumped, as `gmail-cli-oauth>=1.5.0` was for
  `html`/`cc`.)
- Live tests are `tests/test_live.py`, gated by
  `pytest.mark.skipif(not os.getenv("GOOGLE_MCP_LIVE"), ...)`. The other live
  scripts (`tests/live_sheets_editing.py`, `tests/live_sheets_formatting.py`)
  are not `test_*`-named, so pytest never collects them.
- Fakes: exactly one hand-written fake, `FakeAPI` in
  `tests/test_gmail_server.py`, mirroring `gmail_cli.api.GmailAPI`. The
  calendar server tests use a bare `MagicMock`; the sheets/docs/drive server
  tests use bare `MagicMock` via a monkeypatched `_api` (plus
  `patch("google_auth_core.get_service", ...)` for wrapper unit tests).

## Part 1: `ci.yml`

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
      - run: pip install -e .[dev]
      - run: ruff check .
      - run: pytest
```

Notes:

- **No secrets.** The suite is unit + in-memory protocol tests; the sibling
  packages come from PyPI. Nothing needs credentials.
- **Live tests are excluded by default**: `GOOGLE_MCP_LIVE` is simply never
  set in the workflow environment, and the skipif gate plus the non-collected
  `live_*.py` naming make this a two-layer guarantee.
- Adding 3.13 to the matrix means also adding the
  `Programming Language :: Python :: 3.13` classifier to `pyproject.toml`
  (and 3.13 must actually pass before the classifier ships).
- `fail-fast: false` so one interpreter's failure doesn't mask another's.

### Lint: ruff, deliberately minimal

CLAUDE.md currently documents "there is no separate lint/typecheck step".
This spec changes that decision on purpose, with the smallest useful rule set:

- Add `ruff>=0.4` to the `dev` extras.
- Configure in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I"]  # ruff defaults + import sorting
```

- One-time cleanup commit: run `ruff check --fix .` and settle any remaining
  manual fixes before the CI workflow lands, so CI is born green.
- **Doc updates are part of this work**: CLAUDE.md's "no lint step" sentence
  and the README testing section change to "pytest + ruff is the gate".
- Type checking stays out (P2).

## Part 2: `release.yml` (Trusted Publishing)

`.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags: ["v*"]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Check tag matches project version
        run: |
          v=$(python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
          [ "v$v" = "${GITHUB_REF_NAME}" ] || { echo "tag ${GITHUB_REF_NAME} != version $v"; exit 1; }
      - run: pip install build && python -m build
      - uses: actions/upload-artifact@v4
        with: { name: dist, path: dist/ }

  publish:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write   # OIDC for Trusted Publishing
    steps:
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - uses: pypa/gh-action-pypi-publish@release/v1
```

- **Trusted Publishing (OIDC) replaces the Keychain token for CI releases.**
  No API token is stored in GitHub. The existing local flow (Keychain token,
  manual `twine upload`) remains as a documented fallback for emergencies.
- The tag/version check step prevents the classic mistake of tagging without
  bumping `pyproject.toml`.
- The `pypi` GitHub environment gives an audit point and can later carry a
  required-reviewer rule if wanted.

### PyPI trusted-publisher setup checklist (one-time, manual)

- [ ] Log in to pypi.org as the `google-workspace-suite-mcp` owner.
- [ ] Project page: Manage, then Publishing.
- [ ] Add a new GitHub publisher: owner `nitaiaharoni1`, repository
      `google-workspace-mcp`, workflow `release.yml`, environment `pypi`.
- [ ] In the GitHub repo settings, create the `pypi` environment.
- [ ] Dry-run: bump to a `.dev` version on a branch, tag, confirm the publish
      job authenticates (or use TestPyPI with a second publisher entry first).

## Part 3: the FakeAPI drift guard

Two mechanisms, matched to the two faking styles actually in the tests.

### 3a. Signature-parity test for hand-written fakes (P0)

New file `tests/test_fake_drift.py`. A pairs table maps each hand-written
fake to the real wrapper it mirrors; today that table has one row:

```python
PAIRS = [
    ("tests.test_gmail_server", "FakeAPI", "gmail_cli.api", "GmailAPI"),
]
```

For each pair, for every method defined *directly on the fake class*
(`vars(Fake)`, callable, name not starting with `_`):

1. **Existence**: the real class must have a callable attribute of the same
   name. Catches real-wrapper renames/removals.
2. **No unknown parameters**: every parameter name in the fake's signature
   must exist in the real method's signature (unless the real method takes
   `**kwargs`). Catches the dangerous direction: a fake accepting arguments
   the real wrapper would reject with a TypeError.
3. **Required coverage**: every required parameter of the real method (no
   default, not `*args`/`**kwargs`, `self` excluded) must be present in the
   fake's signature. The fake may declare it with a default; that is
   accepted. Catches fakes that under-declare and would mask a missing
   required argument.

The compatibility rule is **name-based, not position-based**: server wrappers
pass keyword arguments throughout, so positional-order drift is out of scope.
Comparing default *values* (e.g. a fake claiming `format="metadata"` when the
real default became `"full"`) is P1, behind a small allowlist, because default
drift is behavioral rather than structural and needs case-by-case judgment.

Implementation notes:

- Uses `inspect.signature` on the **unbound class functions**; the guard
  imports classes and never instantiates them. This matters because the real
  wrappers' `__init__` may resolve accounts or build authorized services;
  class-level inspection touches no auth and no network, so the test runs in
  plain `pytest` with zero setup.
- `__init__` and underscore-prefixed helpers on the fake (e.g. `_record`) are
  excluded by the selection rule above.
- Failures name the method and the offending parameter, e.g.
  `FakeAPI.send_message has parameter 'html_body' unknown to GmailAPI.send_message`.

### 3b. Spec-pinned mocks for MagicMock-based tests (P1)

Bare `MagicMock` cannot drift-fail because it accepts everything. Replace the
server-test mocks with spec'd mocks:

```python
fake = MagicMock(spec=CalendarAPI)        # calendar
fake_api = MagicMock(spec=SheetsAPI)      # sheets; same for DocsAPI, DriveAPI
```

A spec'd mock raises on calls to nonexistent methods and (with
`create_autospec` or method-level autospec) on signature-violating calls.
Plan: start with `spec=` (attribute existence, cheap, zero test rewrites),
and evaluate `create_autospec(..., instance=True)` (full signature
enforcement) as a follow-up, since autospec can slow collection and is
noisier to adopt. Importing `CalendarAPI` from `google_calendar_cli.api` for
spec purposes is import-only and safe, same argument as 3a.

## Requirements summary

| Priority | Item |
|---|---|
| P0 | `ci.yml`: pytest matrix 3.10-3.13, push/PR to main, no secrets |
| P0 | `tests/test_fake_drift.py` signature-parity guard (rules 1-3) |
| P0 | `release.yml`: tag-triggered build + Trusted Publishing, tag/version check |
| P0 | PyPI trusted-publisher configured; manual Keychain flow demoted to fallback |
| P1 | ruff in dev extras + CI, minimal rule set; CLAUDE.md/README gate wording updated |
| P1 | 3.13 classifier added once the matrix is green |
| P1 | `spec=`-pinned MagicMocks in calendar/sheets/docs/drive server tests |
| P1 | Default-value comparison in the drift guard (allowlisted) |
| P2 | Type checking (mypy or pyright) |
| P2 | `create_autospec` upgrade for full mock signature enforcement |
| P2 | README CI badge (valuable once the repo is public) |

## Testing

The drift guard is itself a test, so its verification is a deliberate-drift
canary, run during development and then reverted:

1. Add a bogus parameter to `FakeAPI.send_message` in a scratch commit:
   the guard must fail with rule 2 naming `send_message` and the parameter.
2. Remove a required parameter from the fake (e.g. drop `to`): the guard
   must fail with rule 3.
3. Point the pairs table at a method that does not exist on `GmailAPI`
   (rename `get_profile` on the fake to `get_profilee`): rule 1 fails.
4. Revert; guard green; full `pytest` green.

Workflow verification:

- `ci.yml`: open a scratch PR touching a comment; all four matrix jobs run
  and pass; confirm the job env contains no `GOOGLE_MCP_LIVE` and the pytest
  summary shows `test_live.py` tests skipped.
- `release.yml`: verify the tag/version mismatch step fails on a deliberately
  wrong tag before trusting it; then do one real (or TestPyPI) release.

## Out of scope

- Coverage measurement and thresholds.
- Publishing the sibling packages (`google-auth-core`, `gmail-cli-oauth`,
  `google-calendar-cli`) from this repo's CI; they release independently.
- Making the GitHub repo public (tracked below).
- Windows/macOS CI runners; the servers are OS-independent Python and
  ubuntu-only keeps minutes cheap. Revisit if an OS-specific bug ever shows.

## Open questions

- **Repo visibility** (owner decision, non-blocking for CI, blocking for the
  badge's value): `pyproject.toml` already advertises
  `https://github.com/nitaiaharoni1/google-workspace-mcp` on PyPI, and that
  link 404s for everyone else while the repo is private. Recommendation:
  make it public alongside the first badge-bearing release.
- **Actions minutes** (owner, non-blocking): private-repo CI consumes the
  free-plan minute quota; the suite is small, but if the matrix grows,
  consider trimming to 3.10 + 3.13 on PRs and full matrix on main.
- **TestPyPI first?** (owner, non-blocking): whether to wire a TestPyPI
  publisher for release-workflow rehearsal or accept the first live tag as
  the rehearsal.
