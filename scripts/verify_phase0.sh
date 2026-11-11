#!/usr/bin/env bash

# Verify the Phase 0 bootstrap exit criteria without changing project files.
set -uo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

passed=0
failed=0

check() {
    local label="$1"
    shift
    if "$@"; then
        printf 'PASS: %s\n' "$label"
        passed=$((passed + 1))
    else
        printf 'FAIL: %s\n' "$label"
        failed=$((failed + 1))
    fi
}

has_package_metadata() {
    grep -Eiq '^name[[:space:]]*=[[:space:]]*"[^"]*scalping[^"]*"' pyproject.toml &&
        grep -Eq '^requires-python[[:space:]]*=[[:space:]]*">=3\.12"' pyproject.toml &&
        grep -Eq '^version[[:space:]]*=[[:space:]]*"[^"]+"' pyproject.toml &&
        grep -Eq '^description[[:space:]]*=[[:space:]]*"[^"]+"' pyproject.toml
}

has_topology() {
    grep -Fq 'Python 3.12' FOREX_SCALPING_MASTER_PLAN.md &&
        grep -Fq '127.0.0.1' FOREX_SCALPING_MASTER_PLAN.md &&
        grep -Fq 'Architecture C' FOREX_SCALPING_MASTER_PLAN.md &&
        grep -Fq 'MT5 runs on Windows' FOREX_SCALPING_MASTER_PLAN.md
}

has_independence_evidence() {
    grep -Fq 'project path is independent' FOREX_SCALPING_MASTER_PLAN.md &&
        grep -Fq 'No external production system or database may be reused' FOREX_SCALPING_MASTER_PLAN.md
}

has_consistent_source_docs() {
    test -s FOREX_SCALPING_MASTER_PLAN.md &&
        test -s TRADING_STRATEGY_DESIGN.md &&
        grep -Eiq 'canonical for phase status|master plan remains canonical for phase status' TRADING_STRATEGY_DESIGN.md &&
        grep -Eiq 'safety gates' TRADING_STRATEGY_DESIGN.md
}

has_no_external_system_references() {
    local matches
    matches="$(rg -n -i \
        --glob '*.{py,toml,yml,yaml,json,ini,cfg,sh}' \
        --glob '!**/.specify/**' \
        --glob '!**/scripts/verify_phase0.sh' \
        '(docker-compose|docker compose|mt5[-_ ]bridge|existing[-_ ](trading[-_ ])?system|shared[-_ ]database)' \
        src mql5 tests migrations prototypes pyproject.toml 2>/dev/null || true)"
    if [[ -n "$matches" ]]; then
        printf '%s\n' "$matches" >&2
        return 1
    fi
}

has_expected_git_state() {
    git rev-parse --git-dir >/dev/null 2>&1 || return 1
    local log status
    log="$(git log --oneline -1 2>&1)"
    status="$(git status --porcelain)"
    [[ "$log" == *'does not have any commits yet'* && -n "$status" ]] ||
        [[ -z "$log" && -n "$status" ]]
}

check 'Git repository exists and git status runs' bash -c 'git rev-parse --git-dir >/dev/null 2>&1 && git status --short >/dev/null 2>&1'
check 'pyproject.toml declares scalping package metadata and Python >=3.12' has_package_metadata
check 'master plan exists and is non-empty' test -s FOREX_SCALPING_MASTER_PLAN.md
check 'strategy design exists and is non-empty' test -s TRADING_STRATEGY_DESIGN.md
check 'source documents agree on status authority and safety gates' has_consistent_source_docs
check 'approved topology is recorded in master plan' has_topology
check 'Phase 0 independence exit evidence is recorded' has_independence_evidence
check 'project code/config has no external trading-system references' has_no_external_system_references
check 'repository remains uncommitted with untracked project files' has_expected_git_state

printf '\nPhase 0 verification: %d passed, %d failed\n' "$passed" "$failed"
(( failed == 0 ))
