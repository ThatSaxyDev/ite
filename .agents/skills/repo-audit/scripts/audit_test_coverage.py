#!/usr/bin/env python3
"""Audit test coverage by identifying untested code patterns."""

import argparse
import json
import os
import re
import sys


def find_untested_files_python(root_dir="."):
    """Find Python files without corresponding test files."""
    py_files = []
    test_files = []

    for dirpath, _, filenames in os.walk(root_dir):
        if "/venv/" in dirpath or "/node_modules/" in dirpath or "/.git/" in dirpath:
            continue
        for f in filenames:
            if f.endswith(".py"):
                if f.startswith("test_") or "_test.py" in f:
                    test_files.append(os.path.join(dirpath, f))
                else:
                    py_files.append(os.path.join(dirpath, f))

    untested = []
    for py_file in py_files:
        base = os.path.splitext(py_file)[0]
        test_variants = [
            base.replace("/", "/test_") + ".py",
            base + "_test.py",
            os.path.join(os.path.dirname(base), "test_" + os.path.basename(base) + ".py"),
        ]
        if not any(t in test_files for t in test_variants):
            untested.append(py_file)

    return {"untested": untested, "test_count": len(test_files)}


def find_untested_files_js(root_dir="."):
    """Find JS/TS files without corresponding test files."""
    src_files = []
    test_files = []

    for dirpath, _, filenames in os.walk(root_dir):
        if "/node_modules/" in dirpath or "/.git/" in dirpath or "/dist/" in dirpath or "/build/" in dirpath:
            continue
        for f in filenames:
            if f.endswith((".js", ".ts", ".jsx", ".tsx")):
                if ".test." in f or ".spec." in f:
                    test_files.append(os.path.join(dirpath, f))
                elif not f.startswith("index."):
                    src_files.append(os.path.join(dirpath, f))

    untested = []
    for src_file in src_files:
        base = os.path.splitext(src_file)[0]
        test_variants = [
            base + ".test.js",
            base + ".test.ts",
            base + ".test.jsx",
            base + ".test.tsx",
            base + ".spec.js",
            base + ".spec.ts",
        ]
        if not any(t in test_files for t in test_variants):
            untested.append(src_file)

    return {"untested": untested, "test_count": len(test_files)}


def count_assertions_in_file(filepath):
    """Count assertion patterns in a test file."""
    content = open(filepath, "r", encoding="utf-8", errors="ignore").read()

    patterns = [
        r"assertEqual",
        r"assert\b",
        r"\.toBe\(",
        r"\.toEqual\(",
        r"\.toContain\(",
        r"\.toMatch\(",
        r"expect\(",
    ]

    count = 0
    for pattern in patterns:
        count += len(re.findall(pattern, content))
    return count


def audit_test_coverage(directory=".", language=None, output_format="text"):
    """Run full test coverage audit."""
    results = {"language": language or "auto", "directory": directory}

    if language == "python" or language is None:
        py_results = find_untested_files_python(directory)
        results["python"] = py_results
        results["python"]["low_assertion_files"] = []
        for tf in py_results.get("test_files", []):
            if count_assertions_in_file(tf) < 3:
                results["python"]["low_assertion_files"].append(tf)

    if language == "js" or language is None:
        js_results = find_untested_files_js(directory)
        results["javascript"] = js_results
        results["javascript"]["low_assertion_files"] = []
        for tf in js_results.get("test_files", []):
            if count_assertions_in_file(tf) < 3:
                results["javascript"]["low_assertion_files"].append(tf)

    if output_format == "json":
        print(json.dumps(results, indent=2))
    else:
        print("=" * 60)
        print("TEST COVERAGE AUDIT REPORT")
        print("=" * 60)

        if "python" in results:
            print(f"\n[PYTHON] {len(results['python']['untested'])} files without tests")
            for f in results["python"]["untested"][:10]:
                print(f"  - {f}")
            if len(results["python"]["untested"]) > 10:
                print(f"  ... and {len(results['python']['untested']) - 10} more")

        if "javascript" in results:
            print(f"\n[JAVASCRIPT] {len(results['javascript']['untested'])} files without tests")
            for f in results["javascript"]["untested"][:10]:
                print(f"  - {f}")
            if len(results["javascript"]["untested"]) > 10:
                print(f"  ... and {len(results['javascript']['untested']) - 10} more")

    return results


def main():
    parser = argparse.ArgumentParser(description="Audit test coverage")
    parser.add_argument("--python", action="store_true", help="Focus on Python")
    parser.add_argument("--js", action="store_true", help="Focus on JavaScript/TypeScript")
    parser.add_argument("--output", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("directory", nargs="?", default=".", help="Directory to scan")

    args = parser.parse_args()

    lang = None
    if args.python:
        lang = "python"
    elif args.js:
        lang = "js"

    audit_test_coverage(args.directory, lang, args.output)


if __name__ == "__main__":
    main()
