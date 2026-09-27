"""Step 1 of the Laya-vs-Qwen headline comparison (runs in the project venv).

Collects the real Google News headlines the pipeline used for a few analysis dates,
classifies them and the hand-labelled set with the local qwen3:8b through Ollama
(constrained to three labels), and writes everything to a JSON file that
probe_laya_compare.py (Laya venv) then classifies too.

    python scripts/probe_headlines_qwen.py OUT.json
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta

from backend.app.execution.news_pt import fetch_news_pt

sys.path.insert(0, "scripts")
from headline_data import LABELLED  # noqa: E402  (same hand-labelled set)

MODEL = "qwen3:8b"
LABELS = ["positivo", "negativo", "neutro"]
DATES = ["2026-05-18", "2026-07-06", "2026-08-17"]


def qwen_label(headline: str) -> tuple[str, float]:
    body = {
        "model": MODEL, "stream": False, "think": False, "options": {"temperature": 0},
        "format": {"type": "object", "properties": {"sentimento": {"type": "string", "enum": LABELS}}, "required": ["sentimento"]},
        "messages": [{"role": "user", "content": f"Qual o efeito provável desta manchete sobre o preço da ação da empresa citada? Responda positivo, negativo ou neutro.\n\nManchete: {headline}"}],
    }
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    reply = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return json.loads(reply["message"]["content"])["sentimento"], time.perf_counter() - started


def headlines_for(date: str) -> list[str]:
    start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    block = fetch_news_pt("PETR4.SA", start_date=start, end_date=date, limit=12)
    return [line.split("] ", 1)[1].rsplit(" - ", 1)[0] for line in block.splitlines() if line.startswith("  [")]


def main(out_path: str) -> None:
    data = {"labelled": [], "real": []}
    for text, gold in LABELLED:
        label, secs = qwen_label(text)
        data["labelled"].append({"text": text, "gold": gold, "qwen": label, "qwen_s": secs})
    for date in DATES:
        for text in headlines_for(date):
            label, secs = qwen_label(text)
            data["real"].append({"date": date, "text": text, "qwen": label, "qwen_s": secs})
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    hits = sum(1 for r in data["labelled"] if r["qwen"] == r["gold"])
    avg = sum(r["qwen_s"] for r in data["labelled"] + data["real"]) / max(1, len(data["labelled"]) + len(data["real"]))
    print(f"qwen3:8b nas manchetes rotuladas: {hits}/{len(data['labelled'])} | manchetes reais coletadas: {len(data['real'])} | {avg:.1f}s por manchete")


if __name__ == "__main__":
    main(sys.argv[1])
