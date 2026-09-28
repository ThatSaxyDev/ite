#!/usr/bin/env python3
"""Find common bug patterns in source code."""

import argparse
import json
import os
import re
import sys


# Bug patterns by language and severity
BUG_PATTERNS = {
    "python": {
        "critical": [
            {
                "name": "Hardcoded Secret",
                "pattern": r"(password|secret|key|token)\s*=\s*['\"][^'\"]+['\"]",
                "description": "Potential hardcoded secret detected"
            },
            {
                "name": "SQL Injection Risk",
                "pattern": r"(?:execute|query|raw)\s*\([^)]*%\s*(?:%s|d|f|r)",
                "description": "Potential SQL injection via string formatting"
            },
            {
                "name": "Eval Usage",
                "pattern": r"\beval\s*\(",
                "description": "eval() can execute arbitrary code"
            },
        ],
        "high": [
            {
                "name": "Bare Except",
                "pattern": r"except\s*:",
                "description": "Bare except clause catches all exceptions including SystemExit"
            },
            {
                "name": "Mutable Default Argument",
                "pattern": r"def\s+\w+\s*\([^)]*=\s*(?:\[|\{)",
                "description": "Mutable default argument - shared across calls"
            },
            {
                "name": "Unclosed File",
                "pattern": r"=\s*open\s*\([^)]+\)(?!\s+as)",
                "description": "File opened without context manager - potential resource leak"
            },
        ],
        "medium": [
            {
                "name": "Unused Import",
                "pattern": r"^import\s+(\w+)",
                "description": "Import might be unused"
            },
            {
                "name": "TODO/FIXME",
                "pattern": r"#\s*(TODO|FIXME|XXX|HACK)",
                "description": "Pending work item"
            },
            {
                "name": "Broad Exception",
                "pattern": r"except\s+(Exception|BaseException)",
                "description": "Catching broad exception classes"
            },
        ],
        "low": [
            {
                "name": "Debug Print",
                "pattern": r"\b(print|console\.log)\s*\(",
                "description": "Debug print statement in code"
            },
            {
                "name": "Long Method",
                "description": "Method is very long"
            },
        ]
    },
    "javascript": {
        "critical": [
            {
                "name": "Hardcoded Secret",
                "pattern": r"(password|secret|key|token)\s*[=:]\s*['\"][^'\"]+['\"]",
                "description": "Potential hardcoded secret detected"
            },
            {
                "name": "Eval Usage",
                "pattern": r"\beval\s*\(|\.execScript\s*\(",
                "description": "eval() can execute arbitrary code"
            },
            {
                "name": "InnerHTML XSS",
                "pattern": r"\.innerHTML\s*=",
                "description": "innerHTML can lead to XSS if user input is included"
            },
        ],
        "high": [
            {
                "name": "Missing Error Handler",
                "pattern": r"\.then\s*\([^)]+\)(?!\.catch)",
                "description": "Promise without error handling"
            },
            {
                "name": "Unterminated String",
                "pattern": r"['\"][^'\"]*$",
                "description": "Potential unterminated string"
            },
            {
                "name": "== Instead of ===",
                "pattern": r"\b==\b(?!\=)",
                "description": "Loose equality can cause type coercion issues"
            },
        ],
        "medium": [
            {
                "name": "Unused Variable",
                "pattern": r"(?:const|let|var)\s+(\w+)",
                "description": "Variable might be unused"
            },
            {
                "name": "TODO/FIXME",
                "pattern": r"(?:\/\/|\/\*)\s*(TODO|FIXME|XXX|HACK)",
                "description": "Pending work item"
            },
        ],
        "low": [
            {
                "name": "Console Log",
                "pattern": r"console\.(log|debug|info|warn|error)\s*\(",
                "description": "Console statement in code"
            },
            {
                "name": "Var Usage",
                "pattern": r"\bvar\s+",
                "description": "Consider using let or const instead of var"
            },
        ]
    },
    "go": {
        "critical": [
            {
                "name": "Hardcoded Secret",
                "pattern": r"(?i)(password|secret|key|token)\s*[=:]\s*['\"][^'\"]+['\"]",
                "description": "Potential hardcoded secret detected"
            },
        ],
        "high": [
            {
                "name": "Unchecked Error",
                "pattern": r"[^!]=\s+.*\(\)\s*(?!\s*//|[^!]\S+",
                "description": "Error return value might be unchecked"
            },
            {
                "name": "Goroutine Leak",
                "pattern": r"go\s+\w+\s*\(",
                "description": "Goroutine without context or cancellation"
            },
        ],
        "medium": [
            {
                "name": "TODO/FIXME",
                "pattern": r"\/\/\s*(TODO|FIXME|XXX|HACK)",
                "description": "Pending work item"
            },
        ],
    }
}


def find_bugs_in_file(filepath, lang, severity_filter=None):
    """Find bug patterns in a single file."""
    issues = []

    if lang not in BUG_PATTERNS:
        return issues

    # Skip test files and generated code
    if "/test" in filepath or ".test." in filepath or filepath.endswith("_test.py"):
        return issues

    try:
        content = open(filepath, "r", encoding="utf-8", errors="ignore").read()
        lines = content.split("\n")
    except Exception:
        return issues

    for sev_level in ["critical", "high", "medium", "low"]:
        if severity_filter and sev_level != severity_filter:
            continue

        patterns = BUG_PATTERNS[lang].get(sev_level, [])
        for pattern_def in patterns:
            if "pattern" not in pattern_def:
                continue

            pattern = pattern_def["pattern"]
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line):
                    issues.append({
                        "file": filepath,
                        "line": i,
                        "severity": sev_level,
                        "name": pattern_def["name"],
                        "description": pattern_def["description"],
                        "code": line.strip()[:80]
                    })

    return issues


def scan_directory(directory, lang, severity=None):
    """Scan a directory for bugs."""
    all_issues = []

    extensions = {
        "python": [".py"],
        "javascript": [".js", ".ts", ".jsx", "tsx"],
        "go": [".go"]
    }

    for dirpath, _, filenames in os.walk(directory):
        # Skip common non-source directories
        if any(d in dirpath for d in ["/.", "node_modules", "vendor", "venv", "__pycache__", ".git"]):
            continue

        for f in filenames:
            if any(f.endswith(ext) for ext in extensions.get(lang, [])):
                filepath = os.path.join(dirpath, f)
                issues = find_bugs_in_file(filepath, lang, severity)
                all_issues.extend(issues)

    return all_issues


def main():
    parser = argparse.ArgumentParser(description="Find common bug patterns")
    parser.add_argument("--lang", choices=["python", "js", "ts", "javascript", "go"],
                        required=True, help="Target language")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"],
                        help="Filter by severity")
    parser.add_argument("--output", choices=["text", "json"], default="text",
                        help="Output format")
    parser.add_argument("--list-patterns", action="store_true",
                        help="List available patterns and exit")
    parser.add_argument("directory", nargs="?", default=".", help="Directory to scan")

    args = parser.parse_args()

    # Normalize language name
    lang = args.lang
    if lang in ("js", "ts"):
        lang = "javascript"

    if args.list_patterns:
        print(f"Available patterns for {lang}:")
        if lang in BUG_PATTERNS:
            for sev in ["critical", "high", "medium", "low"]:
                patterns = BUG_PATTERNS[lang].get(sev, [])
                if patterns:
                    print(f"\n[{sev.upper()}]")
                    for p in patterns:
                        print(f"  - {p['name']}: {p['description']}")
        else:
            print("  No patterns defined for this language")
        return

    issues = scan_directory(args.directory, lang, args.severity)

    if args.output == "json":
        print(json.dumps(issues, indent=2))
    else:
        # Group by severity
        grouped = {"critical": [], "high": [], "medium": [], "low": []}
        for issue in issues:
            grouped[issue["severity"]].append(issue)

        print("=" * 70)
        print("BUG PATTERN ANALYSIS")
        print("=" * 70)

        for sev in ["critical", "high", "medium", "low"]:
            sev_issues = grouped[sev]
            if sev_issues:
                print(f"\n[{sev.upper()}] {len(sev_issues)} issues found")
                print("-" * 70)
                for issue in sev_issues[:20]:  # Limit output
                    print(f"  {issue['file']}:{issue['line']}")
                    print(f"    {issue['name']}: {issue['description']}")
                    if issue['code']:
                        print(f"    Code: {issue['code']}")
                    print()

                if len(sev_issues) > 20:
                    print(f"  ... and {len(sev_issues) - 20} more")

        total = len(issues)
        if total == 0:
            print("\n✅ No bug patterns detected!")
        else:
            print(f"\nTotal issues found: {total}")
            if grouped["critical"] or grouped["high"]:
                print("⚠️  Address critical/high severity issues before merging")


if __name__ == "__main__":
    main()
