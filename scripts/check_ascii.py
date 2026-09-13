#!/usr/bin/env python3
"""Fail if any submitted file contains non-ASCII characters.

Course submissions (discussion posts, assignment notebooks) are kept plain
ASCII so em dashes and curly quotes never leak into Canvas or Turnitin.
Usage: python scripts/check_ascii.py FILE [FILE ...]
"""

import sys

bad = 0
for path in sys.argv[1:]:
    with open(path, "rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            for offset, byte in enumerate(line):
                if byte > 127:
                    print(f"{path}:{line_number}:{offset + 1}: non-ASCII byte 0x{byte:02x}")
                    bad += 1
                    break
sys.exit(1 if bad else 0)
