# Feature Specification: Fix Phase 0 Python Version Gate

**Feature Branch**: `011-fix-python-version-gate`

**Created**: 2026-11-11

**Status**: Draft

**Input**: Corrective feature for Phase 0 Python-version exit-gate
failure. The package manifest declares `requires-python = ">=3.10"`
but Phase 0 spec FR-002 and SC-001 require `>=3.12`. The verification
script already checks for `>=3.12` and correctly reports FAIL. This
spec covers the metadata fix, validation consistency, evidence
recording, and master-plan status update.

**Parent Spec**: `specs/001-phase0-bootstrap/spec.md` (FR-002, SC-001)

## User Scenarios & Testing

### User Story 1 — Package Manifest Declares Python 3.12 (Priority: P1)

The project owner reads `pyproject.toml` and confirms that the
`requires-python` field declares `>=3.12`, matching the constitution's
Principle I and Phase 0 FR-002.

**Why this priority**: This is the root cause of the exit-gate
failure. Every other correction depends on the manifest being fixed
first.

**Independent Test**: Read `pyproject.toml` and verify the
`requires-python` value is exactly `">=3.12"`.

**Acceptance Scenarios**:

1. **Given** `pyproject.toml` in the project root, **When** the
   `requires-python` field is read, **Then** its value is `">=3.12"`.
2. **Given** the updated `pyproject.toml`, **When** compared against
   Phase 0 spec FR-002 ("Python 3.12 requirement"), **Then** the
   manifest satisfies the requirement.

---

### User Story 2 — Quickstart Validation Checks Exact Version (Priority: P1)

The project owner runs the quickstart validation and sees a specific
check that verifies the `requires-python` value is `>=3.12`, not
merely that a Python version string exists somewhere in the manifest.

**Why this priority**: The original quickstart step 2 used
`grep -q "python"` which would pass on any mention of "python" —
it did not verify the version. The check must be precise enough to
catch the exact failure that occurred.

**Independent Test**: Run the quickstart validation step for
`pyproject.toml` and confirm it checks the exact `requires-python`
value `>=3.12`.

**Acceptance Scenarios**:

1. **Given** the updated quickstart.md, **When** the package manifest
   validation step is read, **Then** it checks that `requires-python`
   equals `">=3.12"` (not just that the word "python" appears).
2. **Given** a `pyproject.toml` with `requires-python = ">=3.10"`,
   **When** the quickstart validation step is applied, **Then** it
   reports FAIL.
3. **Given** a `pyproject.toml` with `requires-python = ">=3.12"`,
   **When** the quickstart validation step is applied, **Then** it
   reports PASS.

---

### User Story 3 — Verification Script Consistent (Priority: P1)

The project owner runs `scripts/verify_phase0.sh` and sees
consistent results: the script's `has_package_metadata` function
checks for `>=3.12`, the quickstart checks for `>=3.12`, and both
agree on PASS or FAIL.

**Why this priority**: The verification script already checks for
`>=3.12` correctly. After the manifest fix, the script and the
quickstart must both report PASS — any inconsistency between the two
would undermine confidence in the evidence.

**Independent Test**: Run `scripts/verify_phase0.sh` after the
manifest fix and confirm the `pyproject.toml` check reports PASS.

**Acceptance Scenarios**:

1. **Given** the manifest is updated to `>=3.12`, **When**
   `scripts/verify_phase0.sh` runs, **Then** the "pyproject.toml
   declares scalping package metadata and Python >=3.12" check
   reports PASS.
2. **Given** the script and quickstart both check for `>=3.12`,
   **When** both are run, **Then** they agree on the result (both
   PASS or both FAIL — no split verdict).

---

### User Story 4 — Evidence Recorded and Status Distinguished (Priority: P2)

The project owner reviews the quickstart success summary and sees
that completed checks are recorded with their actual result (PASS or
FAIL), and that the overall Phase 0 status is determined by whether
all exit checks pass — not by whether checks were merely executed.

**Why this priority**: The previous quickstart recorded a FAIL in
the summary table but the master plan still said "Complete with
repository hygiene outstanding." Completed checks and passed exit
criteria are distinct: a check can complete with a FAIL result. The
master plan status must reflect whether all checks actually passed.

**Independent Test**: After the manifest fix, run the verifier,
update the quickstart summary with actual results, and confirm the
master plan Phase 0 status is updated only if every check passes.

**Acceptance Scenarios**:

1. **Given** the verification script has run, **When** the quickstart
   success summary is updated, **Then** every row shows the actual
   PASS/FAIL result from the latest run.
2. **Given** the quickstart summary shows all PASS, **When** the
   master plan Phase 0 status is reviewed, **Then** it reflects that
   all exit checks have passed.
3. **Given** any quickstart check shows FAIL, **When** the master
   plan Phase 0 status is reviewed, **Then** it does NOT claim the
   phase is complete or that all exit criteria are met.

---

### Edge Cases

- What if the manifest fix introduces a version that the current
  WSL Python (3.10.12) does not satisfy? The metadata declares the
  project's target, not the current environment. A `pip install -e .`
  on 3.10 will refuse; this is correct behavior per the constitution.
  The spec does not require the environment to be upgraded — only
  that the manifest is correct.
- What if `scripts/verify_phase0.sh` has other unrelated failures?
  Only the `pyproject.toml` check is in scope for this corrective
  feature. Other failures are reported but not addressed here.
- What if the quickstart summary previously recorded results that
  are now stale? All rows must reflect the latest verifier run, not
  a mix of historical and current results.

## Requirements

### Functional Requirements

- **FR-001**: `pyproject.toml` MUST set `requires-python = ">=3.12"`
  to satisfy Phase 0 spec FR-002 and Constitution Principle I.
- **FR-002**: The quickstart validation step for `pyproject.toml`
  MUST check that `requires-python` is exactly `">=3.12"`, not
  merely that a Python-related string exists in the file.
- **FR-003**: `scripts/verify_phase0.sh` MUST remain consistent with
  the quickstart validation — both MUST check for `>=3.12` and
  produce agreeing results.
- **FR-004**: After the manifest fix, `scripts/verify_phase0.sh`
  MUST be rerun and its output recorded as evidence.
- **FR-005**: The quickstart success summary MUST distinguish between
  "check was executed" and "check passed" — every row MUST show the
  actual PASS or FAIL result from the latest verifier run.
- **FR-006**: The master plan Phase 0 status MUST be updated to
  reflect all exit checks passing, only if every check in the
  verifier reports PASS.
- **FR-007**: This corrective feature MUST NOT modify application
  trading code, broker adapters, database schemas or migrations,
  or any source file under `src/` or `mql5/`.
- **FR-008**: This corrective feature MUST NOT stage files, create
  commits, or push to any remote.

### Key Entities

- **Package Manifest**: `pyproject.toml` — the `requires-python`
  field is the sole code change.
- **Verification Script**: `scripts/verify_phase0.sh` — already
  checks for `>=3.12`; rerun to produce evidence.
- **Quickstart Validation**: `specs/001-phase0-bootstrap/quickstart.md`
  — step 2 and the success summary table.
- **Master Plan Status**: `FOREX_SCALPING_MASTER_PLAN.md` Phase 0
  section — status line updated only if all checks pass.

## Success Criteria

### Measurable Outcomes

- **SC-001**: `grep -E '^requires-python' pyproject.toml` returns
  `requires-python = ">=3.12"`.
- **SC-002**: The quickstart validation step for the package manifest
  specifically checks the `>=3.12` value and would reject `>=3.10`.
- **SC-003**: `scripts/verify_phase0.sh` reports PASS for the
  pyproject.toml check after the fix.
- **SC-004**: The quickstart success summary table shows the actual
  latest result for every row, with zero stale entries.
- **SC-005**: The master plan Phase 0 status accurately reflects
  whether all exit checks passed, and does not conflate "checks ran"
  with "checks passed."

## Assumptions

- The verification script (`scripts/verify_phase0.sh`) is already
  correct — it checks for `>=3.12`. No changes to the script's
  logic are needed; only a rerun to produce updated evidence.
- The current WSL environment runs Python 3.10.12. This corrective
  feature does not upgrade the environment; that is a separate
  operational task. The manifest declares the project target per the
  constitution.
- No other Phase 0 exit checks are failing. If other failures are
  discovered during the rerun, they are reported but not fixed by
  this feature.
- The quickstart step 2 is the only validation step that needs
  tightening. All other quickstart steps already check for specific
  values.
- The `description` field in `pyproject.toml` may also be stale
  ("Non-trading domain foundation") but updating it is out of scope
  for this narrowly scoped corrective feature unless it causes a
  verifier failure.
