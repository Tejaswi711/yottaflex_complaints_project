#!/usr/bin/env python3
"""Step 10: generate the dataset twice with the same seed and compare row counts + SHA-256 checksums.

    python check_reproducibility.py                       # full size
    python check_reproducibility.py --complaints 200 --customers 500 --orders 800 --messages 600
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile


def run(extra, folder):
    subprocess.run([sys.executable, "generate_data.py", "--out", folder] + extra, check=True,
                   stdout=subprocess.DEVNULL)
    with open(os.path.join(folder, "manifest.json")) as fh:
        m = json.load(fh)
    return m["row_counts"], m["sha256"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="output/reproducibility_report.json")
    args, extra = ap.parse_known_args()
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        rows1, sums1 = run(extra, a)
        rows2, sums2 = run(extra, b)
    same_rows, same_sums = rows1 == rows2, sums1 == sums2
    report = {"generator_args": extra, "runs": 2, "row_counts_identical": same_rows,
              "checksums_identical": same_sums, "row_counts": rows1, "sha256_run1": sums1, "sha256_run2": sums2}
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", newline="\n") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    print("row counts identical :", same_rows)
    print("checksums identical  :", same_sums, f"({len(sums1)} files compared)")
    sys.exit(0 if same_rows and same_sums else 1)


if __name__ == "__main__":
    main()
