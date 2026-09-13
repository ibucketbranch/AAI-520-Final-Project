#!/usr/bin/env python3
"""Fail if a dev notebook carries outputs or execution counts.

nbstripout strips outputs on commit; this is the second line of defense so a
notebook that slipped past the hook (or was added with -f) still fails CI.
Usage: python scripts/check_notebooks_clean.py NOTEBOOK [NOTEBOOK ...]
Exits 0 when given no arguments so empty globs pass.
"""

import json
import sys

bad = 0
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as handle:
        notebook = json.load(handle)
    for index, cell in enumerate(notebook.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        if cell.get("outputs"):
            print(f"{path}: cell {index} has outputs")
            bad += 1
        if cell.get("execution_count") is not None:
            print(f"{path}: cell {index} has an execution_count")
            bad += 1
sys.exit(1 if bad else 0)
