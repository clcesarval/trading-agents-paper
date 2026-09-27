"""One-off migration: regenerate every already-resolved reflection in
memory.md with the corrected scoring prompt (see
backend/app/analysis/memory_feedback.py:install_fixed_reflection_prompt).

Why this exists: the old prompt asked "was the directional call correct?"
without ever stating that a Hold neither gains nor loses from a move it
didn't participate in — so a Hold whose stock happened to rise got reflected
on as "the directional call was correct". That wrong lesson (e.g. "+5.4% vs
SPY... the directional call was correct") then kept reinforcing exactly the
conservative-Hold bias future runs' Portfolio Manager prompt reads back via
get_past_context(), regardless of the prompt fix going forward — the fix
only affects NEW reflections, not the ~57 already written to disk.

Run once, from the repo root: python scripts/fix_memory_reflections.py
Back up data/tradingagents/memory.md first (this rewrites it in place).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.analysis.memory_feedback import MEMORY_LOG_PATH, install_fixed_reflection_prompt  # noqa: E402
from backend.app.config import settings  # noqa: E402


def main() -> None:
    from tradingagents.agents.utils.memory import TradingMemoryLog
    from tradingagents.graph.reflection import Reflector
    from tradingagents.llm_clients import create_llm_client

    install_fixed_reflection_prompt()
    llm = create_llm_client(
        provider="ollama", model=settings.ollama_model,
        base_url=f"{settings.ollama_base_url.rstrip('/')}/v1", temperature=settings.llm_temperature,
    ).get_llm()
    reflector = Reflector(llm)

    log_path = Path(MEMORY_LOG_PATH)
    text = log_path.read_text(encoding="utf-8")
    sep = TradingMemoryLog._SEPARATOR
    blocks = text.split(sep)

    new_blocks = []
    regenerated = 0
    skipped = 0
    for block in blocks:
        stripped = block.strip()
        if not stripped:
            new_blocks.append(block)
            continue
        lines = stripped.splitlines()
        tag_line = lines[0].strip()
        if not (tag_line.startswith("[") and tag_line.endswith("]")) or tag_line.endswith("| pending]"):
            new_blocks.append(block)  # pending or malformed — leave untouched
            continue
        fields = [f.strip() for f in tag_line[1:-1].split("|")]
        if len(fields) < 5:
            new_blocks.append(block)
            continue
        date, ticker, rating, raw_pct, alpha_pct = fields[0], fields[1], fields[2], fields[3], fields[4]
        body = "\n".join(lines[1:])
        if "REFLECTION:" not in body:
            new_blocks.append(block)
            continue
        decision_part, _, _old_reflection = body.partition("REFLECTION:")
        decision_text = decision_part.strip()
        if decision_text.startswith("DECISION:"):
            decision_text = decision_text[len("DECISION:"):].strip()
        try:
            raw = float(raw_pct.rstrip("%")) / 100
            alpha = float(alpha_pct.rstrip("%")) / 100
        except ValueError:
            print(f"skip (unparseable return) {date} {ticker} raw={raw_pct!r} alpha={alpha_pct!r}")
            new_blocks.append(block)
            skipped += 1
            continue

        new_reflection = reflector.reflect_on_final_decision(decision_text, raw, alpha, benchmark_name="^BVSP")
        new_block = f"{tag_line}\n\n{decision_part.strip()}\n\nREFLECTION:\n{new_reflection}"
        new_blocks.append(new_block)
        regenerated += 1
        print(f"[{regenerated}] {date} {ticker} {rating} raw={raw_pct} alpha={alpha_pct} -> {new_reflection[:100]}")

    new_text = sep.join(new_blocks)
    tmp_path = log_path.with_suffix(".tmp")
    tmp_path.write_text(new_text, encoding="utf-8")
    tmp_path.replace(log_path)
    print(f"\nDone: {regenerated} reflections regenerated, {skipped} skipped (unparseable).")


if __name__ == "__main__":
    main()
