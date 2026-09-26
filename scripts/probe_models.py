"""Quick model probe: does a local model return the Portfolio Manager's structured
decision, and does it commit to a direction when the evidence is one-sided?

Uses the project's own pieces (create_llm_client, bind_structured, PortfolioDecision
and the real Portfolio Manager prompt), so a pass here means the same call works in
the pipeline. Takes seconds per model instead of 10-15 min per full backtest date.

    python scripts/probe_models.py qwen3:14b qwen3:8b phi4-mini
"""
from __future__ import annotations

import sys
import time

from tradingagents.agents.schemas import PortfolioDecision
from tradingagents.agents.utils.structured import NO_EXTERNAL_TOOLS, bind_structured
from tradingagents.llm_clients.factory import create_llm_client

BASE_URL = "http://localhost:11434/v1"

SCENARIOS = {
    "ALTA (evidencia clara de compra)": (
        "Aggressive: PETR4 broke above its 200-day average on rising volume, MACD turned positive, oil is up 6% this "
        "month, and the company just announced a record production milestone plus a higher dividend. Momentum and "
        "fundamentals align; the upside to 46 is well supported.\n"
        "Conservative: Some pullback risk after a 9% run, but there is no negative catalyst; stop below 40 covers it.\n"
        "Neutral: Evidence is one-sided in favor of adding exposure; the risk/reward is clearly favorable."
    ),
    "QUEDA (evidencia clara de venda)": (
        "Aggressive: There is nothing to buy here. PETR4 lost its 200-day average on heavy volume, MACD is deeply "
        "negative, oil fell 11% this month, and the government signaled a dividend cut and price controls.\n"
        "Conservative: Every signal points down: trend, momentum, commodity and policy. Reduce exposure now.\n"
        "Neutral: I cannot find a single supportive argument; the evidence clearly favors cutting the position."
    ),
    "EQUILIBRADO (deveria ser Hold)": (
        "Aggressive: Oil is firm but the stock is stuck in a range with mixed volume.\n"
        "Conservative: Political risk on dividends offsets the solid cash flow; nothing new either way.\n"
        "Neutral: Bulls and bears are evenly matched; no catalyst to change exposure."
    ),
}


def build_prompt(history: str) -> str:
    return f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

The instrument to analyze is `PETR4.SA`. Company: Petrobras. Analysis date: 2026-07-06.

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

**Context:**
- Research Manager's investment plan: **Follow the evidence in the debate.**
- Trader's transaction proposal: **Follow the evidence in the debate.**

**Risk Analysts Debate History:**
{history}

---

Ground every conclusion in specific evidence from the analysts. Commit to a directional call only when the evidence clearly supports one; choose Hold when the case is balanced, materially conflicting, ambiguous, or insufficient to justify changing exposure, rather than forcing a direction to appear decisive. Weigh the analysts on their merits, independent of speaking order.

{NO_EXTERNAL_TOOLS}Write the answer in Portuguese."""


def probe(model: str) -> None:
    print(f"\n=== {model} ===", flush=True)
    llm = create_llm_client("ollama", model, base_url=BASE_URL, temperature=0, timeout=300).get_llm()
    structured = bind_structured(llm, PortfolioDecision, "Portfolio Manager")
    if structured is None:
        print("  bind_structured: NAO suportado por este modelo", flush=True)
        return
    for name, history in SCENARIOS.items():
        started = time.perf_counter()
        try:
            result = structured.invoke(build_prompt(history))
            took = time.perf_counter() - started
            if result is None:
                print(f"  {name:36s} FALHOU (sem resultado estruturado)  {took:5.0f}s", flush=True)
            else:
                print(f"  {name:36s} OK  rating={result.rating.value:12s} {took:5.0f}s", flush=True)
        except Exception as exc:  # noqa: BLE001 - report every failure mode
            took = time.perf_counter() - started
            print(f"  {name:36s} FALHOU {type(exc).__name__}: {str(exc).splitlines()[0][:90]}  {took:5.0f}s", flush=True)


if __name__ == "__main__":
    for model in sys.argv[1:] or ["qwen3:14b"]:
        probe(model)
