#!/usr/bin/env python3
"""Verify a packaged APK asset is byte-identical to its source file (CRC32 + size).

The stale-APK trap (CLAUDE.md "Shell & Gradle invocation"): a rebuild can
silently repackage a stale asset or native lib, and a green on-device run then
exercises old content. For `reference_track.wav` the failure is extra silent
because regenerating the asset does not change its SIZE (the lead-in is mixed
in place), so only a content hash catches a stale copy. Run this after every
asset regeneration + rebuild, before `adb install`.

Exits 0 and prints both CRCs when they match; exits 1 with a STALE message
when they differ or the asset is missing from the APK.

Usage (defaults are the harness reference-track case):
    python harness/scripts/verify_apk_asset.py
    python harness/scripts/verify_apk_asset.py --apk path/to.apk \
        --asset assets/foo.bin --source path/to/foo.bin
"""

from __future__ import annotations

import argparse
import zipfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_APK = REPO_ROOT / "harness" / "build" / "outputs" / "apk" / "debug" / "harness-debug.apk"
DEFAULT_ASSET = "assets/reference_track.wav"
DEFAULT_SOURCE = REPO_ROOT / "harness" / "src" / "main" / "assets" / "reference_track.wav"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", default=str(DEFAULT_APK), help="APK to inspect")
    parser.add_argument("--asset", default=DEFAULT_ASSET, help="entry name inside the APK")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="source file the asset must match")
    args = parser.parse_args()

    with zipfile.ZipFile(args.apk) as z:
        try:
            info = z.getinfo(args.asset)
        except KeyError:
            print(f"STALE: {args.asset} is not in {args.apk}")
            return 1
    src = Path(args.source).read_bytes()
    src_crc = zlib.crc32(src)

    print(f"APK asset:  size {info.file_size:>10}  crc {info.CRC:08x}  ({args.asset})")
    print(f"source:     size {len(src):>10}  crc {src_crc:08x}  ({args.source})")
    if info.file_size != len(src) or info.CRC != src_crc:
        print("STALE: packaged asset differs from the source file -- clean-rebuild before installing")
        return 1
    print("OK: packaged asset is byte-identical to the source file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
