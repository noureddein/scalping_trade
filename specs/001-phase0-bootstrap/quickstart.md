# Quickstart Validation: Phase 0 — Project Bootstrap

**Date**: 2026-11-11

## Prerequisites

- Access to the project directory on WSL2
- Git installed
- Ability to read `pyproject.toml`

## Validation Steps

### 1. Verify standalone project directory

```bash
# Confirm the project exists at its own path
ls -la /home/noureddein/my_projects/scalping_trade/

# Confirm .git directory exists
test -d .git && echo "PASS: Git repository exists" || echo "FAIL"
```

**Expected**: Directory listing shows project files; Git repo confirmed.

### 2. Verify package manifest

```bash
# Check pyproject.toml exists and declares requires-python >= 3.12
test -f pyproject.toml && echo "PASS: pyproject.toml exists" || echo "FAIL"
grep -Eq '^requires-python[[:space:]]*=[[:space:]]*">=3\.12"' pyproject.toml \
  && echo "PASS: requires-python = \">=3.12\"" \
  || echo "FAIL: requires-python is not \">=3.12\""
```

**Expected**: `pyproject.toml` exists and `requires-python` is exactly `">=3.12"`.

### 3. Verify source-of-truth documents

```bash
# Both documents must exist and be non-empty
test -s FOREX_SCALPING_MASTER_PLAN.md && echo "PASS: Master plan exists" || echo "FAIL"
test -s TRADING_STRATEGY_DESIGN.md && echo "PASS: Strategy design exists" || echo "FAIL"
```

**Expected**: Both files exist and are non-empty.

### 4. Verify topology is recorded

```bash
# Search for the approved topology declaration
grep -c "127.0.0.1" FOREX_SCALPING_MASTER_PLAN.md
grep -c "Architecture C" FOREX_SCALPING_MASTER_PLAN.md
grep -c "Python 3.12" FOREX_SCALPING_MASTER_PLAN.md
```

**Expected**: Each grep returns at least 1 match.

### 5. Verify project independence

```bash
# Search for references to the existing trading system
# Replace "existing_system_path" with the actual path if known
grep -r "docker-compose" . --include="*.py" --include="*.toml" --include="*.yml" | grep -v ".specify" | wc -l
```

**Expected**: Zero references to the existing trading system's Docker
config, database, or MT5 bridge.

### 6. Verify repository hygiene state

```bash
git status
git log --oneline 2>&1 | head -5
```

**Expected**: All files untracked; no commits (or only owner-authorized
commits).

## Success Summary

| Check | Criteria | Status |
|-------|----------|--------|
| Standalone directory | `.git` exists, own path | PASS |
| Package manifest | `pyproject.toml` with `requires-python = ">=3.12"` | PASS |
| Master plan | Exists, non-empty | PASS |
| Strategy design | Exists, non-empty, defers to master plan | PASS |
| Topology recorded | §14.1 has WSL+MT5+TCP+ArchC | PASS |
| Independence | Zero cross-references | PASS |
| Repo hygiene | Untracked, no unauthorized commits | PASS |

**Observed run**: `scripts/verify_phase0.sh` — 9 passed, 0 failed (2026-11-11).
