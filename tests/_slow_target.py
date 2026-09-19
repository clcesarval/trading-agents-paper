"""Standalone picklable target for the multiprocessing timeout test.

Must live in its own top-level module (not a closure/lambda) so the spawn
context can import it by reference in the child process.
"""
import time


def slow_worker(payload, queue):
    time.sleep(payload.get("sleep_seconds", 5))
    queue.put({"kind": "result", "signal": "Hold", "is_review": False, "decision_text": "concluido"})
    queue.put({"kind": "__done__"})
