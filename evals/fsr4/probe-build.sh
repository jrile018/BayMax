#!/usr/bin/env bash
# CPU-only cross build. Does not start Wine, D3D12, Vulkan or enumerate devices.
set -euo pipefail
base="$(cd "$(dirname "$0")/../.." && pwd)"
probe="$base/evals/fsr4"
root="$base/platform/runtime/win64/root"
sdk="$base/platform/runtime/sdk/headers"
out="$probe/probe-build"
mkdir -p "$out"
g++ -std=c++17 -O2 -Wall -Wextra -Werror "$probe/probe-helper-tests.cpp" -o "$out/probe-helper-tests"
"$out/probe-helper-tests"
python3 "$probe/probe-json-tests.py"
compiler=""
for candidate in "$root/usr/bin/x86_64-w64-mingw32-g++-posix" "$root/usr/bin/x86_64-w64-mingw32-g++-win32"; do
    if [[ -f "$candidate" ]]; then compiler="$candidate"; break; fi
done
[[ -n "$compiler" ]] || { echo 'isolated MinGW compiler unavailable' >&2; exit 2; }
gccdir="$(find "$root/usr/lib/gcc/x86_64-w64-mingw32" -name cc1plus -printf '%h\n' | sort | head -1)"
[[ -n "$gccdir" ]] || { echo 'isolated cc1plus unavailable' >&2; exit 2; }
# Prefer frontend and compiler runtime variants that match.
case "$gccdir" in *posix*) compiler="$root/usr/bin/x86_64-w64-mingw32-g++-posix";; *win32*) compiler="$root/usr/bin/x86_64-w64-mingw32-g++-win32";; esac
export LD_LIBRARY_PATH="$root/usr/lib/x86_64-linux-gnu:$root/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$compiler" --version | head -1
"$compiler" --sysroot="$root" -B"$gccdir/" -B"$root/usr/x86_64-w64-mingw32/bin/" \
    -idirafter "$root/usr/x86_64-w64-mingw32/include" \
    -isystem "$sdk/api/include" -isystem "$sdk/upscalers/include" \
    -L"$root/usr/x86_64-w64-mingw32/lib" -L"$gccdir" \
    -std=c++17 -O2 -Wall -Wextra -Werror -municode -static -static-libgcc -static-libstdc++ \
    "$probe/probe.cpp" -o "$out/probe.exe" -ld3d12 -ldxgi -ldxguid
file "$out/probe.exe"
sha256sum "$probe/probe.cpp" "$probe/probe-helpers.h" "$out/probe.exe"
