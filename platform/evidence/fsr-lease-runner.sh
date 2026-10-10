#!/usr/bin/env bash
# Execute only after an external Observer02 FSR lease and exact-source review.
set -euo pipefail
unset LD_PRELOAD LD_AUDIT
cd /workspace/knight26/worktrees/amd
run_id="$FSR_RUN_ID"
lease_json="$FSR_LEASE_JSON"
reviewed_sha="$FSR_REVIEWED_RUNNER_SHA256"
if [[ ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; then
    echo "invalid FSR run id" >&2
    exit 2
fi
evidence="$(realpath -e -- platform/evidence)"
runs="$(realpath -e -- platform/evidence/fsr-runs)"
run="$(realpath -e -- "platform/evidence/fsr-runs/$run_id")"
if [[ "$runs" != "$evidence/fsr-runs" || "$run" != "$runs/$run_id" ||
      ! -d "$run/prefix" || -L "$run/prefix" ||
      "$(realpath -e -- "$run/prefix")" != "$run/prefix" ]]; then
    echo "FSR run must be a prepared private evidence directory" >&2
    exit 2
fi
log="$run/shell.log"
if [[ -e "$log" || -L "$log" ]]; then
    echo "refusing to overwrite prior shell log" >&2
    exit 2
fi
receipt="$run/execute-runner.json"
if [[ -e "$receipt" || -L "$receipt" ]]; then
    echo "refusing prior execution receipt" >&2
    exit 2
fi
server=""
wine_root="$(realpath -m -- platform/runtime/win64/root)"
for candidate in platform/runtime/win64/root/usr/lib/x86_64-linux-gnu/wine/wineserver platform/runtime/win64/root/usr/lib/wine/wineserver64 platform/runtime/win64/root/usr/bin/wineserver; do
    if [[ -f "$candidate" ]]; then
        resolved="$(realpath -e -- "$candidate")"
        if [[ "$resolved" == "$wine_root/"* ]]; then server="$resolved"; break; fi
    fi
done
cleanup() {
    [[ -n "$server" ]] || return 0
    [[ -d "$run/prefix" && ! -L "$run/prefix" ]] || return 0
    [[ "$(realpath -e -- "$run/prefix")" == "$run/prefix" ]] || return 0
    receipt="$run/execute-runner.json"
    [[ -f "$receipt" && ! -L "$receipt" ]] || return 0
    attempted="$(
        OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 \
        taskset -c 0,1 /opt/venv/bin/python -c \
        'import json,sys; r=json.load(open(sys.argv[1])); assert r.get("run_id")==sys.argv[2]; print("1" if any(p.get("attempted") is True for p in r.get("phases",{}).values()) else "0")' \
        "$receipt" "$run_id" 2>/dev/null
    )" || return 0
    [[ "$attempted" == 1 ]] || return 0
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
    timeout --signal=TERM --kill-after=2s 10s taskset -c 0,1 env -i \
        PATH=/usr/bin:/bin LANG=C.UTF-8 \
        OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
        WINEPREFIX="$run/prefix" XDG_CACHE_HOME="$run/cache" \
        LD_LIBRARY_PATH="/workspace/knight26/worktrees/amd/platform/runtime/win64/root/usr/lib/x86_64-linux-gnu/wine/x86_64-unix:/workspace/knight26/worktrees/amd/platform/runtime/win64/root/usr/lib/x86_64-linux-gnu:/workspace/knight26/worktrees/amd/platform/runtime/win64/root/lib/x86_64-linux-gnu" \
        "$server" -k >> "$run/wineserver-cleanup.log" 2>&1 || true
}
trap cleanup EXIT
set +e
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 \
timeout --signal=TERM --kill-after=5s 280s taskset -c 0,1 /opt/venv/bin/python \
    platform/evidence/fsr-lease-runner.py --execute-authorized-lease \
    --run-id "$run_id" --reviewed-runner-sha256 "$reviewed_sha" --lease-json "$lease_json" \
    > "$log" 2>&1
result=$?
printf '\nEXIT_CODE:%s\n' "$result" >> "$log"
exit "$result"
