#!/usr/bin/env python3
"""
scripts/verify_review_tests.py
Verifies that the reviewer test files tests/test_review_round1.py and tests/test_review_round2.py
have not been edited, renamed, moved, or deleted, and match their exact required SHA-256 digests.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

EXPECTED_HASHES = {
    "tests/test_review_round1.py": "721a82f0bc8eb3dd2f9f9bd196761e7a585113ec81076c467eb9928dae2a09d6",
    "tests/test_review_round2.py": "604e60f709f1963d7b98e740c7603d3d2736904a555ffd240bda23404f6815bd",
}

ROOT = Path(__file__).resolve().parent.parent


def verify() -> bool:
    all_ok = True
    for rel_path, expected_hash in EXPECTED_HASHES.items():
        file_path = ROOT / rel_path
        if not file_path.is_file():
            print(f"FAIL: {rel_path} does not exist!", file=sys.stderr)
            all_ok = False
            continue
        content = file_path.read_bytes()
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            print(f"FAIL: {rel_path} SHA-256 mismatch!\n  Expected: {expected_hash}\n  Actual:   {actual_hash}", file=sys.stderr)
            all_ok = False
        else:
            print(f"OK: {rel_path} verified ({actual_hash[:8]}...)")
    return all_ok


if __name__ == "__main__":
    if not verify():
        sys.exit(1)
    print("All review test files verified byte-for-byte.")
