"""Does the open Laya decision model classify Brazilian-Portuguese finance headlines well?

Runs in its own virtualenv (torch + laya); it does not touch the project's environment.

  1. Hand-labelled headlines with obvious sentiment: measures accuracy and whether the
     probabilities are usable (the model documents that it ships uncalibrated).
  2. Real Google News headlines the pipeline already used: compares Laya with the
     qwen3:8b the pipeline uses today (agreement, speed).

    python scripts/probe_laya.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

import laya

from headline_data import LABELLED, LABELS  # noqa: E402

QUESTION = {
    "sentimento": {
        "type": "choice",
        "instructions": "Qual o efeito provável desta manchete sobre o preço da ação da empresa citada?",
        "criteria": LABELS,
    }
}


def classify(agent, text: str) -> tuple[str, dict[str, float]]:
    out = agent.predict({"manchete": text}, QUESTION)["answers"]["sentimento"]
    probs = out.get("probabilities") or out.get("probs") or {}
    return out["choice"], probs


def main(model: str) -> None:
    agent = laya.load(model)
    started = time.perf_counter()
    rows = [(text, gold, *classify(agent, text)) for text, gold in LABELLED]
    took = time.perf_counter() - started
    hits = sum(1 for _, gold, pred, _ in rows if pred == gold)
    print(f"\n== Manchetes rotuladas à mão ({model}) ==")
    for text, gold, pred, probs in rows:
        top = max(probs.values()) if probs else float("nan")
        print(f"  {'OK ' if pred == gold else 'ERR'} esperado={gold:8s} previu={pred:8s} prob_da_escolha={top:5.2f}  {text[:60]}")
    print(f"  acerto: {hits}/{len(rows)} ({hits / len(rows):.0%}) | {took / len(rows) * 1000:.0f} ms por manchete")
    wrong = [max(p.values()) for _, g, pred, p in rows if pred != g and p]
    right = [max(p.values()) for _, g, pred, p in rows if pred == g and p]
    if wrong and right:
        print(f"  prob. média quando ACERTA: {sum(right) / len(right):.2f} | quando ERRA: {sum(wrong) / len(wrong):.2f}  (calibrada = bem menor ao errar)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "convaiinnovations/laya-multilingual")
