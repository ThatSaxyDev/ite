"""Evaluate token savings from the tool optimizer.

Usage:
    python scripts/_eval_optimizer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ite.config.config import Config, ToolOptimizerConfig
from ite.tools.builtin import get_all_builtin_tools
from ite.tools.optimizer import compact_description, compact_line_number_prefix


# ── token counter (char-based fallback if tiktoken unavailable) ──────────────────
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def ct(text: str) -> int:
        return len(_enc.encode(text))
except ImportError:
    def ct(text: str) -> int:
        return len(text) // 4


# ── 1. Tool schema comparison ────────────────────────────────────────────────────
def eval_tool_schemas() -> None:
    config_off = Config(tool_optimizer=ToolOptimizerConfig(enabled=False))
    config_on = Config(tool_optimizer=ToolOptimizerConfig(enabled=True))

    tools_on = [t(config_on) for t in get_all_builtin_tools()]
    tools_off = [t(config_off) for t in get_all_builtin_tools()]

    total_on = 0
    total_off = 0

    print("=" * 72)
    print("1. TOOL SCHEMA TOKENS (all tools combined)")
    print("=" * 72)
    print(f"{'Tool':<28} {'Original':>8} {'Compact':>8} {'Saved':>8} {'%':>7}")
    print("-" * 72)

    for tool_off, tool_on in zip(tools_off, tools_on):
        schema_off = tool_off.to_openai_schema()
        schema_on = tool_on.to_openai_schema()
        tok_off = ct(str(schema_off))
        tok_on = ct(str(schema_on))
        saved = tok_off - tok_on
        pct = (saved / max(tok_off, 1)) * 100

        total_off += tok_off
        total_on += tok_on

        if saved > 0:
            print(f"  {tool_off.name:<26} {tok_off:>8} {tok_on:>8} {saved:>8} {pct:>6.0f}%")

    print("-" * 72)
    pct_total = ((total_off - total_on) / max(total_off, 1)) * 100
    print(f"  {'TOTAL':<26} {total_off:>8} {total_on:>8} {total_off - total_on:>8} {pct_total:>6.0f}%")
    print()


# ── 2. Individual description compression ─────────────────────────────────────────
def eval_descriptions() -> None:
    print("=" * 72)
    print("2. DESCRIPTION COMPRESSION (per-tool)")
    print("=" * 72)
    print(f"{'Tool':<28} {'Original':>8} {'Compact':>8} {'Saved':>8}")
    print("-" * 72)

    config = Config()
    for tool_cls in get_all_builtin_tools():
        tool = tool_cls(config)
        desc = tool.description
        compact = compact_description(desc)
        tok_off = ct(desc)
        tok_on = ct(compact)
        saved = tok_off - tok_on
        if saved > 0:
            print(f"  {tool.name:<26} {tok_off:>8} {tok_on:>8} {saved:>8}")
    print()


# ── 3. Read output compaction ─────────────────────────────────────────────────────
def eval_read_output() -> None:
    print("=" * 72)
    print("3. READ OUTPUT COMPACTION (simulated 200-line file)")
    print("=" * 72)

    # Build a realistic sample: comment-heavy Python-like file
    sample_lines = []
    for i in range(1, 201):
        line = f'{"    " if i % 4 == 0 else ""}x = {i}  # line {i:03d} {"-" * 20}'
        sample_lines.append(line)
    sample = "\n".join(sample_lines)

    # Original format: 6-char prefix
    original = "\n".join(f"{i:6}|{line}" for i, line in enumerate(sample_lines, 1))
    if len(sample_lines) > 1:
        header = f"Showing lines 1 to {len(sample_lines)} of 500\n\n"
        original = header + original

    # Compact format: 4-char prefix + terse header
    compact = "\n".join(f"{i:4}|{line}" for i, line in enumerate(sample_lines, 1))
    if len(sample_lines) > 1:
        compact = f"# 1-{len(sample_lines)}/500\n\n" + compact

    tok_orig = ct(original)
    tok_cpt = ct(compact)
    saved = tok_orig - tok_cpt
    pct = (saved / max(tok_orig, 1)) * 100

    print(f"  Original header + output:  {tok_orig:>8} tokens")
    print(f"  Compact header + output:   {tok_cpt:>8} tokens")
    print(f"  Saved:                      {saved:>8} tokens ({pct:.0f}%)")
    print()


# ── 4. Edit line-range savings ────────────────────────────────────────────────────
def eval_line_range() -> None:
    print("=" * 72)
    print("4. EDIT LINE-RANGE SAVINGS (simulated 500-line file)")
    print("=" * 72)

    lines = [f"def process_{i}(): return {i}  # helper fn\n" for i in range(1, 501)]
    full_content = "".join(lines)

    # Scenario: model wants to edit lines 55-64
    full_old_string = "".join(lines[54:64]).rstrip("\n")
    range_old_string = "55-64"

    tok_full = ct(full_old_string)
    tok_range = ct(range_old_string)

    print(f"  old_string (10 lines of text):  {tok_full:>8} tokens")
    print(f"  old_string ('55-64'):           {tok_range:>8} tokens")
    print(f"  Saved:                           {tok_full - tok_range:>8} tokens ({(tok_full - tok_range) / max(tok_full, 1) * 100:.0f}%)")
    print()


# ── MAIN ───────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    eval_descriptions()
    eval_tool_schemas()
    eval_read_output()
    eval_line_range()
