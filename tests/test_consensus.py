from backend.app.analysis.consensus import summarize_consensus


def _run(decision, confidence=None):
    return {"decision": decision, "confidence_pct": confidence}


def test_a_clear_majority_reports_the_winner_and_its_average_confidence():
    attempts = [_run("BUY", 60), _run("BUY", 84), _run("HOLD", 66)]
    result = summarize_consensus(attempts)
    assert result["decision"] == "BUY" and result["runs"] == 3
    assert result["agreement"] == round(2 / 3, 2)
    assert result["confidence_pct"] == 72  # average of the two BUY confidences
    assert "Consenso" in result["note"] and "BUY" in result["note"]


def test_the_real_case_of_2026_08_17_had_no_consensus():
    # Real case: Buy, Hold, Hold, Buy across four attempts for the same date.
    attempts = [_run("BUY", 54), _run("HOLD", 66), _run("HOLD", 100), _run("BUY", 60)]
    result = summarize_consensus(attempts)
    assert result["decision"] is None
    assert result["votes"] == {"BUY": 2, "HOLD": 2}
    assert "Sem consenso" in result["note"]
    assert result["confidence_pct"] is None


def test_a_three_way_split_is_not_a_majority_even_with_only_three_runs():
    result = summarize_consensus([_run("BUY"), _run("HOLD"), _run("SELL")])
    assert result["decision"] is None and result["agreement"] == round(1 / 3, 2)


def test_inconclusive_attempts_count_as_their_own_outcome_not_a_vote():
    # Two BUYs against one REVIEW is still a strict majority of the attempts
    # that actually produced a rating.
    result = summarize_consensus([_run("BUY"), _run("BUY"), _run(None)])
    assert result["decision"] == "BUY" and result["votes"]["REVIEW"] == 1


def test_all_attempts_inconclusive_has_no_consensus_decision():
    result = summarize_consensus([_run(None), _run(None)])
    assert result["decision"] is None and result["votes"] == {"REVIEW": 2}


def test_two_out_of_two_split_is_not_a_majority():
    result = summarize_consensus([_run("BUY"), _run("SELL")])
    assert result["decision"] is None


def test_a_single_run_is_trivially_its_own_consensus():
    result = summarize_consensus([_run("HOLD", 80)])
    assert result["decision"] == "HOLD" and result["agreement"] == 1.0 and result["confidence_pct"] == 80


def test_no_attempts_gives_no_fabricated_decision():
    result = summarize_consensus([])
    assert result["decision"] is None and result["runs"] == 0
