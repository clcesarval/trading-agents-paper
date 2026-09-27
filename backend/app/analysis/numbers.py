"""Check every number the model wrote against what the data tools actually returned.

A small model can state exact figures (a debt, a margin, a price level) that no tool
ever produced. This module extracts the numeric claims from each stage's text and
matches each one against the numbers found in the run's real sources (tool outputs,
the verified market snapshot, the news headlines). A claim is:

  * verified   - it appears in the sources (allowing for rounding and for units such
                 as "R$ 118,5 bilhões" vs 118500000000.0);
  * derived    - it is a plain difference or sum of two numbers of the verified
                 market snapshot (e.g. the distance from price to a Bollinger band);
  * unverified - nothing in the sources supports it. That does NOT prove it is
                 wrong (a figure can come from a computation this check cannot see),
                 it means the run cannot back it up.

Deliberately ignored, because they are not factual claims: dates, years, percentages
(derived quantities), scores like 7/10, list numbers and small counts, and integers
followed by a time unit ("50 períodos", "3 meses").
"""
from __future__ import annotations

import bisect
import re
from typing import Any

_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUM = re.compile(
    # A number may follow a comma (CSV rows from the data tools); leftmost matching already
    # keeps "1,234" from being read starting at its second half.
    r"(?<![\w])(?P<cur>R\$|US\$|\$)?\s?(?P<neg>[-−])?"
    r"(?P<num>\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s?(?P<word>trilh[õo]es|trilh[ãa]o|trillions?|bilh[õo]es|bilh[ãa]o|billions?|milh[õo]es|milh[ãa]o|millions?|thousands?|mil|bn|bi|mi)\b"
    r"|(?-i:(?P<abbr>MM|B|M|K)\b))?"
    r"(?P<tail>\s?%|\s?/\s?\d+)?",
    re.I,
)
_TIME_WORD = re.compile(
    r"^\s*(dias?|per[ií]odos?|preg[õo]es|meses|m[eê]s|anos?|semanas?|horas?|minutos?|days?|periods?|months?|years?|weeks?|sessions?)\b",
    re.I,
)
_SCALE = {
    "trilhões": 1e12, "trilhoes": 1e12, "trilhão": 1e12, "trilhao": 1e12, "trillion": 1e12, "trillions": 1e12,
    "bilhões": 1e9, "bilhoes": 1e9, "bilhão": 1e9, "bilhao": 1e9, "billion": 1e9, "billions": 1e9, "bn": 1e9, "bi": 1e9, "b": 1e9,
    "milhões": 1e6, "milhoes": 1e6, "milhão": 1e6, "milhao": 1e6, "million": 1e6, "millions": 1e6, "mi": 1e6, "m": 1e6, "mm": 1e6,
    "mil": 1e3, "thousand": 1e3, "thousands": 1e3, "k": 1e3,
}


def _candidates(num: str) -> list[tuple[float, int]]:
    """Possible (value, decimals shown) readings of a number in PT or EN formatting."""
    has_dot, has_comma = "." in num, "," in num
    if has_dot and has_comma:
        decimal_sep = "." if num.rfind(".") > num.rfind(",") else ","
        other = "," if decimal_sep == "." else "."
        whole, _, frac = num.replace(other, "").partition(decimal_sep)
        return [(float(f"{whole}.{frac}"), len(frac))]
    sep = "." if has_dot else "," if has_comma else ""
    if not sep:
        return [(float(num), 0)]
    parts = num.split(sep)
    if len(parts) > 2:  # 1.234.567 -> thousands separators only
        return [(float("".join(parts)), 0)]
    whole, frac = parts
    if len(frac) == 3 and 1 <= len(whole) <= 3 and not whole.startswith("0"):
        return [(float(whole + frac), 0), (float(f"{whole}.{frac}"), 3)]  # ambiguous: 1.234 could be 1234
    return [(float(f"{whole}.{frac}"), len(frac))]


def _scale(match: re.Match) -> float:
    unit = (match.group("word") or match.group("abbr") or "").lower()
    return _SCALE.get(unit, 1.0)


def extract_claims(text: str) -> list[dict[str, Any]]:
    """Numeric claims worth verifying: [{raw, values: [(value, tolerance)...], context}]."""
    text = _DATE.sub(" ", text or "")
    claims = []
    for m in _NUM.finditer(text):
        if m.group("tail"):
            continue  # percentage or "7/10" score
        if _TIME_WORD.match(text[m.end():m.end() + 16]):
            continue
        scale, cur = _scale(m), bool(m.group("cur"))
        cands = _candidates(m.group("num"))
        has_fraction = any(dec > 0 for _, dec in cands)
        integer_only = not has_fraction and all(float(v).is_integer() for v, _ in cands)
        if not (cur or scale > 1 or has_fraction or (integer_only and max(v for v, _ in cands) >= 1000)):
            continue  # small counts, list numbers, plain integers
        if not cur and scale == 1 and not has_fraction and any(1900 <= v <= 2100 for v, _ in cands):
            continue  # a year
        values = [(v * scale, max(abs(v * scale) * 0.005, 0.5 * (10 ** -dec) * scale)) for v, dec in cands]
        claims.append({"raw": m.group(0).strip(), "values": values, "context": text[max(0, m.start() - 35): m.end() + 25].strip()})
    return claims


def source_numbers(texts: list[str]) -> list[float]:
    """Sorted absolute values of every number in the sources (no eligibility filter)."""
    found: set[float] = set()
    for text in texts:
        for m in _NUM.finditer(_DATE.sub(" ", text or "")):
            scale = _scale(m)
            for value, _ in _candidates(m.group("num")):
                found.add(abs(value * scale))
    return sorted(found)


def _present(sorted_values: list[float], target: float, tol: float) -> bool:
    i = bisect.bisect_left(sorted_values, target - tol)
    return i < len(sorted_values) and sorted_values[i] <= target + tol


def _derived(snapshot_values: list[float], target: float, tol: float) -> bool:
    for i, a in enumerate(snapshot_values):
        for b in snapshot_values[i:]:
            if abs(abs(a - b) - target) <= tol or abs(a + b - target) <= tol:
                return True
    return False


def audit_numbers(stage_texts: dict[str, str], sources: list[str], snapshot: str | None = None, max_items: int = 6) -> dict[str, Any]:
    """Verify every stage's numeric claims. ``stage_texts`` maps stage label -> full text."""
    pool = source_numbers(sources + ([snapshot] if snapshot else []))
    snap = source_numbers([snapshot]) if snapshot else []
    stages, totals = [], {"total": 0, "verified": 0, "derived": 0, "unverified": 0}
    for label, text in stage_texts.items():
        seen, counts, missing = set(), {"total": 0, "verified": 0, "derived": 0, "unverified": 0}, []
        for claim in extract_claims(text):
            if claim["raw"] in seen:
                continue
            seen.add(claim["raw"])
            counts["total"] += 1
            if any(_present(pool, abs(v), tol) for v, tol in claim["values"]):
                counts["verified"] += 1
            elif snap and any(_derived(snap, abs(v), tol) for v, tol in claim["values"]):
                counts["derived"] += 1
            else:
                counts["unverified"] += 1
                missing.append({"raw": claim["raw"], "context": claim["context"]})
        for key in totals:
            totals[key] += counts[key]
        if counts["total"]:
            stages.append({"stage": label, **counts, "missing": missing[:max_items]})
    return {**totals, "stages": stages}
