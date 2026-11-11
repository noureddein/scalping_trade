# Research: Fix Phase 0 Python Version Gate

**Date**: 2026-11-11

No NEEDS CLARIFICATION items in the technical context. This is a
narrowly scoped corrective fix with no design ambiguity. Research
documents the current state and confirms the fix approach.

## Findings

### Current State of `requires-python`

- **Observation**: `pyproject.toml` declares `requires-python = ">=3.10"`.
  The Phase 0 spec FR-002 requires "Python 3.12 requirement."
  Constitution Principle I mandates "Python 3.12 backend running in
  WSL." The verification script `scripts/verify_phase0.sh` already
  checks for `>=3.12` (line 27: `grep -Eq '^requires-python[[:space:]]*=[[:space:]]*">=3\.12"'`)
  and correctly reports FAIL.
- **Decision**: Change `requires-python = ">=3.10"` to
  `requires-python = ">=3.12"` in `pyproject.toml`.
- **Rationale**: The spec and constitution are unambiguous. The
  verification script is already correct. The manifest is the sole
  defect.
- **Alternatives considered**: (a) Keeping `>=3.10` and updating the
  spec/constitution — rejected, the owner explicitly set the 3.12
  requirement. (b) Using `==3.12.*` instead of `>=3.12` — rejected,
  `>=3.12` is the standard PEP 440 floor specifier and matches the
  Phase 0 spec's wording ("Python 3.12 requirement").

### Quickstart Validation Gap

- **Observation**: The Phase 0 quickstart step 2 uses
  `grep -q "python" pyproject.toml` which passes on any mention of
  "python" — it does not verify the version value. The verification
  script is stricter (checks the exact `>=3.12` pattern). This
  inconsistency means the quickstart could report PASS while the
  verifier reports FAIL.
- **Decision**: Update quickstart step 2 to check the exact
  `requires-python = ">=3.12"` value, matching the verifier's logic.
- **Rationale**: The quickstart and verification script must agree.
  The verifier is already correct; the quickstart must be tightened
  to match.
- **Alternatives considered**: Leaving the quickstart as-is and
  relying solely on the verifier — rejected, the quickstart is the
  human-readable validation guide and should catch the same issues.

### Evidence and Status Recording

- **Observation**: The quickstart success summary records
  `FAIL — requires >=3.10` for the package manifest row. The master
  plan Phase 0 status says "Complete with repository hygiene
  outstanding" — it does not mention the manifest failure.
- **Decision**: After the fix, rerun `scripts/verify_phase0.sh`,
  update every row in the quickstart success summary with the actual
  latest result, and update the master plan Phase 0 status only if
  all checks pass.
- **Rationale**: Constitution Principle VIII (Honest Test Reporting)
  requires that results reflect actual test runs. Principle IX
  (Plan-Aligned Evidence) requires that status records have
  verifiable evidence. A check that was executed with a FAIL result
  is not a passed exit criterion.
- **Alternatives considered**: Updating the master plan status
  unconditionally after fixing the manifest — rejected, other checks
  could have regressed; the status must reflect the full verifier
  run.
