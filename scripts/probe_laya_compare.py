"""Step 2 (runs in the Laya venv): classify the same headlines with Laya and compare with Qwen.

    python scripts/probe_laya_compare.py IN.json
"""
from __future__ import annotations

import json
import sys
import time

import laya

from probe_laya import QUESTION, classify  # same question the labelled test used


def main(path: str) -> None:
    data = json.load(open(path, encoding="utf-8"))
    agent = laya.load("convaiinnovations/laya-multilingual")

    print("== Manchetes rotuladas à mão: Laya x Qwen ==")
    laya_hits = qwen_hits = 0
    for row in data["labelled"]:
        row["laya"], probs = classify(agent, row["text"])
        row["laya_p"] = max(probs.values()) if probs else None
        laya_hits += row["laya"] == row["gold"]
        qwen_hits += row["qwen"] == row["gold"]
    n = len(data["labelled"])
    print(f"  Laya acertou {laya_hits}/{n} | Qwen acertou {qwen_hits}/{n}")
    for row in data["labelled"]:
        if row["laya"] != row["gold"] or row["qwen"] != row["gold"]:
            print(f"    esperado={row['gold']:8s} laya={row['laya']:8s} (p={row['laya_p']:.2f}) qwen={row['qwen']:8s}  {row['text'][:58]}")

    print("\n== Manchetes reais do Google News (sem gabarito): concordância ==")
    started = time.perf_counter()
    agree = 0
    by_pair: dict[tuple[str, str], int] = {}
    for row in data["real"]:
        row["laya"], probs = classify(agent, row["text"])
        row["laya_p"] = max(probs.values()) if probs else None
        agree += row["laya"] == row["qwen"]
        by_pair[(row["laya"], row["qwen"])] = by_pair.get((row["laya"], row["qwen"]), 0) + 1
    took = time.perf_counter() - started
    total = len(data["real"])
    print(f"  {total} manchetes | concordam: {agree} ({agree / total:.0%}) | Laya: {took / total * 1000:.0f} ms/manchete")
    print("  (Laya -> Qwen): " + ", ".join(f"{a}->{b}: {c}" for (a, b), c in sorted(by_pair.items(), key=lambda kv: -kv[1])))
    print("\n  Discordâncias:")
    for row in data["real"]:
        if row["laya"] != row["qwen"]:
            print(f"    laya={row['laya']:8s}(p={row['laya_p']:.2f}) qwen={row['qwen']:8s} {row['text'][:78]}")
    qwen_avg = sum(r["qwen_s"] for r in data["real"]) / total
    print(f"\n  Velocidade: Laya {took / total * 1000:.0f} ms | Qwen {qwen_avg * 1000:.0f} ms por manchete")


if __name__ == "__main__":
    main(sys.argv[1])
