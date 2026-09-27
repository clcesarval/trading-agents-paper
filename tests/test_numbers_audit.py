from backend.app.analysis.numbers import audit_numbers, extract_claims, source_numbers

SNAPSHOT = "| Close | 41.18 |\n| close_50_sma | 39.24 |\n| rsi | 56.06 |\n| boll_ub | 42.15 |\n| boll_lb | 39.50 |\n| macd | 0.34 |"


def _raws(text):
    return [c["raw"] for c in extract_claims(text)]


def test_dates_years_percentages_scores_and_small_counts_are_not_claims():
    text = "Em 2026-05-18 o ativo subiu 12% (score 7.0/10) em 3 dias; havia 8 indicadores, 50 períodos e o ano de 2025."
    assert _raws(text) == []


def test_prices_indicators_and_currency_amounts_are_claims():
    raws = _raws("O preço (41.18) está acima da SMA (39.24); dívida de R$ 118,5 bilhões e EBITDA de 51,6B.")
    assert "41.18" in raws and "39.24" in raws
    assert any("118,5" in r for r in raws) and any(r.startswith("51,6") for r in raws)


def test_ticker_and_indicator_names_containing_digits_are_not_claims():
    assert _raws("PETR4.SA e VALE3 com close_50_sma e SMA200 e B3") == []


def test_number_in_the_sources_is_verified_even_across_formats_and_units():
    sources = ["Balance Sheet: Total Debt,118500000000.0,101300000000.0", "Close,41.18"]
    audit = audit_numbers({"Fundamentos": "A dívida é de R$ 118,5 bilhões e o preço 41,18."}, sources)
    assert audit["total"] == 2 and audit["verified"] == 2 and audit["unverified"] == 0


def test_a_figure_no_tool_returned_is_reported_as_unverified_with_its_context():
    audit = audit_numbers({"Decisão": "Stop-loss em R$ 21,50 e alvo em R$ 27,00; fechamento 41.18."}, ["Close,41.18"])
    stage = audit["stages"][0]
    assert audit["unverified"] == 2 and audit["verified"] == 1
    assert {m["raw"] for m in stage["missing"]} == {"R$ 21,50", "R$ 27,00"}
    assert "Stop-loss" in stage["missing"][0]["context"]


def test_plain_differences_of_snapshot_numbers_count_as_derived_not_invented():
    # 42.15 - 41.18 = 0.97 and 41.18 - 39.50 = 1.68 (real case: distance to the Bollinger bands)
    audit = audit_numbers({"Mercado": "A banda superior está 0.97 acima e a inferior 1.68 abaixo."}, [], snapshot=SNAPSHOT)
    assert audit["derived"] == 2 and audit["unverified"] == 0


def test_a_derived_number_only_counts_when_it_really_is_a_difference():
    audit = audit_numbers({"Mercado": "A distância é de 3.33 pontos."}, [], snapshot=SNAPSHOT)
    assert audit["unverified"] == 1 and audit["derived"] == 0


def test_rounding_and_sign_are_tolerated():
    audit = audit_numbers({"Mercado": "MACD de -0.34 e RSI de 56.1"}, [], snapshot=SNAPSHOT)
    assert audit["verified"] == 2  # sign ignored; 56.1 is 56.06 rounded to one decimal


def test_repeated_claim_is_counted_once_per_stage():
    audit = audit_numbers({"Debate": "O preço 41.18 ... de novo 41.18 ... ainda 41.18"}, ["41.18"])
    assert audit["total"] == 1


def test_source_numbers_read_pt_and_en_thousands_and_decimals():
    values = source_numbers(["1.234.567,89 e 2,345.60 e 12,5"])
    assert any(abs(v - 1234567.89) < 1e-6 for v in values)
    assert any(abs(v - 2345.60) < 1e-6 for v in values)
    assert any(abs(v - 12.5) < 1e-6 for v in values)
