# Quickstart Validation: Fix Phase 0 Python Version Gate

**Date**: 2026-11-11

## Prerequisites

- Access to the project directory on WSL2
- `scripts/verify_phase0.sh` exists and is executable

## Validation Steps

### 1. Verify `requires-python` is exactly `>=3.12`

```bash
grep -E '^requires-python' pyproject.toml
```

**Expected**: `requires-python = ">=3.12"`

**FAIL if**: The value is `">=3.10"` or any other version floor.

---

### 2. Verify quickstart step 2 checks the exact value

Read `specs/001-phase0-bootstrap/quickstart.md` step 2 and confirm
it checks for `requires-python = ">=3.12"` specifically, not just
`grep -q "python"`.

**Expected**: The check uses a pattern that would reject `>=3.10`.

---

### 3. Run the verification script

```bash
bash scripts/verify_phase0.sh
```

**Expected**: The "pyproject.toml declares scalping package metadata
and Python >=3.12" check reports PASS. Record the full output.

---

### 4. Verify quickstart success summary is updated

Read the success summary table in
`specs/001-phase0-bootstrap/quickstart.md` and confirm:
- The "Package manifest" row shows PASS (not the old FAIL).
- Every other row shows its actual latest result.
- No stale results remain from prior runs.

---

### 5. Verify master plan Phase 0 status

Read `FOREX_SCALPING_MASTER_PLAN.md` Phase 0 section and confirm:
- If all verifier checks passed: status reflects completion.
- If any check failed: status does NOT claim all exit criteria met.

---

## Success Summary

| Check | Criteria | Expected After Fix |
|-------|----------|--------------------|
| requires-python value | Exactly `">=3.12"` in pyproject.toml | PASS |
| Quickstart step 2 | Checks exact `>=3.12`, rejects `>=3.10` | PASS |
| Verifier pyproject check | `scripts/verify_phase0.sh` PASS on metadata line | PASS |
| Quickstart summary | All rows show latest actual results | PASS |
| Master plan status | Reflects actual verifier outcome | PASS |
| No app code changes | `git diff src/ mql5/` shows zero changes | PASS |
| No git operations | No new commits or staged files | PASS |
