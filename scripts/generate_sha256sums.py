#!/usr/bin/env python3
"""generate_sha256sums.py — Calculates SHA256 hashes for all release artifacts and writes release/SHA256SUMS.txt."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT / "release"
OUTPUT_FILE = RELEASE_DIR / "SHA256SUMS.txt"

INSTALLER_EXTS = {".exe", ".zip", ".appimage", ".deb", ".dmg"}


def compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> int:
    if not RELEASE_DIR.is_dir():
        print(f"[sha256sums] Release dir not found: {RELEASE_DIR}")
        return 1

    artifacts = sorted([
        f for f in RELEASE_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in INSTALLER_EXTS
    ])

    if not artifacts:
        print("[sha256sums] No installer artifacts found in release/")
        return 1

    lines = []
    print(f"[sha256sums] Hashing {len(artifacts)} release artifacts:")
    for art in artifacts:
        digest = compute_sha256(art)
        line = f"{digest}  {art.name}"
        lines.append(line)
        print(f"  {line}")

    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[sha256sums] Wrote {len(lines)} checksums to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
