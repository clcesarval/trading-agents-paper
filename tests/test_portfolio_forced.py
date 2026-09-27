from backend.app.execution.portfolio_forced import detect_rating_mismatch, make_consistent_portfolio_manager

# Real case: PETR4 2026-08-17. The Portfolio Manager's own Executive Summary
# opened with a buy action plan while it stamped Rating: Hold.
_CONTRADICTORY_HOLD = (
    "**Rating**: Hold\n\n"
    "**Executive Summary**: Posicione-se comprando PETR4.SA com alavancagem moderada "
    "(5% do portfólio), priorizando entradas próximas à ruptura da resistência em R$42,15.\n\n"
    "**Investment Thesis**: blah blah."
)

_CONSISTENT_BUY = (
    "**Rating**: Buy\n\n"
    "**Executive Summary**: Posicione-se comprando PETR4.SA com alavancagem moderada.\n\n"
    "**Investment Thesis**: blah blah."
)

_CONSISTENT_HOLD = (
    "**Rating**: Hold\n\n"
    "**Executive Summary**: Mantenha a posição atual e monitore a evolução do RSI antes de agir.\n\n"
    "**Investment Thesis**: blah blah."
)

_HEDGED_HOLD = (
    "**Rating**: Hold\n\n"
    "**Executive Summary**: Considere comprar apenas se o preço confirmar o rompimento da "
    "resistência; por ora, aguarde.\n\n"
    "**Investment Thesis**: blah blah."
)

_CONTRADICTORY_BUY = (
    "**Rating**: Buy\n\n"
    "**Executive Summary**: Venda a posição e reduza a exposição diante da alta volatilidade.\n\n"
    "**Investment Thesis**: blah blah."
)


def test_a_hold_rating_next_to_a_buy_shaped_plan_is_a_mismatch():
    mismatch = detect_rating_mismatch(_CONTRADICTORY_HOLD)
    assert mismatch is not None
    assert mismatch["rating"] == "Hold" and mismatch["direction"] == "compra"


def test_a_buy_rating_next_to_a_buy_shaped_plan_is_consistent():
    assert detect_rating_mismatch(_CONSISTENT_BUY) is None


def test_a_hold_rating_next_to_a_neutral_plan_is_consistent():
    assert detect_rating_mismatch(_CONSISTENT_HOLD) is None


def test_hedged_language_is_not_flagged_as_a_commitment():
    # "considere comprar se confirmar" is not an unhedged action plan — flagging
    # it would punish reasonable cautious language, not an actual contradiction.
    assert detect_rating_mismatch(_HEDGED_HOLD) is None


def test_a_buy_rating_next_to_a_sell_shaped_plan_is_also_a_mismatch():
    mismatch = detect_rating_mismatch(_CONTRADICTORY_BUY)
    assert mismatch is not None and mismatch["direction"] == "venda"


def test_unparseable_text_is_never_flagged():
    assert detect_rating_mismatch("") is None
    assert detect_rating_mismatch("no headers here at all") is None


def test_the_wrapper_asks_for_one_revision_and_uses_it_when_it_fixes_the_contradiction():
    calls = []

    def fake_factory(llm):
        def node(state):
            calls.append(state.get("risk_debate_state", {}).get("history", ""))
            if len(calls) == 1:
                return {"final_trade_decision": _CONTRADICTORY_HOLD, "risk_debate_state": state["risk_debate_state"]}
            return {"final_trade_decision": _CONSISTENT_BUY, "risk_debate_state": state["risk_debate_state"]}
        return node

    events = []
    wrapped_factory = make_consistent_portfolio_manager(fake_factory, lambda kind, text: events.append((kind, text)))
    node = wrapped_factory(llm=None)
    result = node({"risk_debate_state": {"history": "original debate"}})

    assert result["final_trade_decision"] == _CONSISTENT_BUY
    assert len(calls) == 2
    assert "original debate" in calls[1] and "NOTA DO SISTEMA" in calls[1]
    assert any(kind == "warning" and "contradiz" in text for kind, text in events)
    assert any(kind == "config" and "resolveu" in text for kind, text in events)


def test_the_wrapper_keeps_the_original_decision_when_the_retry_still_contradicts_itself():
    def fake_factory(llm):
        def node(state):
            return {"final_trade_decision": _CONTRADICTORY_HOLD, "risk_debate_state": state["risk_debate_state"]}
        return node

    events = []
    wrapped_factory = make_consistent_portfolio_manager(fake_factory, lambda kind, text: events.append((kind, text)))
    node = wrapped_factory(llm=None)
    result = node({"risk_debate_state": {"history": "original debate"}})

    assert result["final_trade_decision"] == _CONTRADICTORY_HOLD  # not silently discarded
    assert any("persistiu" in text for _, text in events)


def test_a_consistent_decision_is_never_retried():
    calls = []

    def fake_factory(llm):
        def node(state):
            calls.append(1)
            return {"final_trade_decision": _CONSISTENT_BUY, "risk_debate_state": state["risk_debate_state"]}
        return node

    wrapped_factory = make_consistent_portfolio_manager(fake_factory, lambda *a: None)
    node = wrapped_factory(llm=None)
    node({"risk_debate_state": {"history": "x"}})

    assert len(calls) == 1
