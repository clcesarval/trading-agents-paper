from backend.app.execution.portfolio_forced import detect_ignored_catalyst, detect_rating_mismatch, make_consistent_portfolio_manager

# Real case: PETR4 2026-08-17, attempt 3 of 3 (after the catalyst-weight rule
# was already in the prompt). The model named its own catalyst "confirmado"
# and still picked Hold instead of following the rule's conclusion.
_IGNORED_BULLISH_CATALYST = (
    "**Rating**: Hold\n\n"
    "**Executive Summary**: Mantenha a posição atual.\n\n"
    "**Investment Thesis**: A dívida líquida é um risco estrutural, mas não um sinal de crise. "
    "O catalisador confirmado (alta no Brent e descoberta de óleo) justifica o Hold, enquanto os "
    "riscos macro são monitorados ativamente."
)

_NAMED_CATALYST_BUT_BUY = (
    "**Rating**: Buy\n\n"
    "**Executive Summary**: Posicione-se comprando PETR4.SA.\n\n"
    "**Investment Thesis**: O catalisador confirmado (descoberta de óleo) justifica o Buy, "
    "aproveitando o momento."
)

_IGNORED_BEARISH_CATALYST = (
    "**Rating**: Hold\n\n"
    "**Executive Summary**: Mantenha a posição atual.\n\n"
    "**Investment Thesis**: O catalisador confirmado (corte de produção e multa regulatória) "
    "justifica cautela, mas os fundamentos de longo prazo sustentam o Hold."
)

_MENTIONS_CATALYST_WORD_BUT_NOT_DATED_OR_CONFIRMED = (
    "**Rating**: Hold\n\n"
    "**Executive Summary**: Mantenha a posição atual.\n\n"
    "**Investment Thesis**: Existe um possível catalisador especulativo (rumor de descoberta), "
    "mas nada confirmado ainda, então o Hold é justificado."
)

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


def test_naming_a_confirmed_bullish_catalyst_and_still_choosing_hold_is_flagged():
    mismatch = detect_ignored_catalyst(_IGNORED_BULLISH_CATALYST)
    assert mismatch is not None
    assert mismatch["kind"] == "ignored_catalyst" and mismatch["expected"] == "Buy/Overweight"
    assert "confirmado" in mismatch["snippet"].lower()


def test_naming_a_confirmed_bearish_catalyst_and_still_choosing_hold_is_flagged():
    mismatch = detect_ignored_catalyst(_IGNORED_BEARISH_CATALYST)
    assert mismatch is not None and mismatch["expected"] == "Sell/Underweight"


def test_a_confirmed_catalyst_that_matches_its_own_bullish_rating_is_not_flagged():
    assert detect_ignored_catalyst(_NAMED_CATALYST_BUT_BUY) is None


def test_a_catalyst_not_labeled_dated_or_confirmed_is_not_flagged():
    # "especulativo" is the opposite of what the rule requires — must not be
    # punished for correctly NOT treating a rumor as a confirmed catalyst.
    assert detect_ignored_catalyst(_MENTIONS_CATALYST_WORD_BUT_NOT_DATED_OR_CONFIRMED) is None


def test_the_plural_form_is_also_caught():
    # Real case: PETR4 2026-08-17, attempt 2 of 3 (after the singular-only
    # regex was already live) — "catalisadores confirmados" (plural) slipped
    # through undetected because the regex only matched the singular form.
    text = (
        "**Rating**: Hold\n\n"
        "**Executive Summary**: Mantenha a posição atual.\n\n"
        "**Investment Thesis**: A evidência é equilibrada, com catalisadores confirmados "
        "(descoberta de petróleo) e riscos estruturais sem novos fatores. Não há consenso "
        "claro para mudar a exposição, justificando o Hold."
    )
    mismatch = detect_ignored_catalyst(text)
    assert mismatch is not None and mismatch["expected"] == "Buy/Overweight"


def test_ignored_catalyst_detector_never_flags_unparseable_text():
    assert detect_ignored_catalyst("") is None
    assert detect_ignored_catalyst("no headers here at all") is None


def test_the_wrapper_also_retries_on_an_ignored_catalyst():
    calls = []

    def fake_factory(llm):
        def node(state):
            calls.append(state.get("risk_debate_state", {}).get("history", ""))
            if len(calls) == 1:
                return {"final_trade_decision": _IGNORED_BULLISH_CATALYST, "risk_debate_state": state["risk_debate_state"]}
            return {"final_trade_decision": _NAMED_CATALYST_BUT_BUY, "risk_debate_state": state["risk_debate_state"]}
        return node

    events = []
    wrapped_factory = make_consistent_portfolio_manager(fake_factory, lambda kind, text: events.append((kind, text)))
    node = wrapped_factory(llm=None)
    result = node({"risk_debate_state": {"history": "original debate"}})

    assert result["final_trade_decision"] == _NAMED_CATALYST_BUT_BUY
    assert len(calls) == 2
    assert "NOTA DO SISTEMA" in calls[1] and "REGRA DE PESO" in calls[1]
    assert any(kind == "warning" and "nomeou um catalisador" in text for kind, text in events)
    assert any(kind == "config" and "resolveu" in text for kind, text in events)


def test_the_catalyst_weight_rule_is_injected_on_every_call_not_just_retries():
    calls = []

    def fake_factory(llm):
        def node(state):
            calls.append(state.get("risk_debate_state", {}).get("history", ""))
            return {"final_trade_decision": _CONSISTENT_HOLD, "risk_debate_state": state["risk_debate_state"]}
        return node

    wrapped_factory = make_consistent_portfolio_manager(fake_factory, lambda *a: None)
    node = wrapped_factory(llm=None)
    node({"risk_debate_state": {"history": "original debate"}})

    assert len(calls) == 1  # a consistent decision is never retried
    assert "original debate" in calls[0]
    assert "REGRA DE PESO" in calls[0] and "catalisador" in calls[0]


def test_the_catalyst_weight_rule_also_carries_into_a_retry(monkeypatch):
    calls = []

    def fake_factory(llm):
        def node(state):
            calls.append(state.get("risk_debate_state", {}).get("history", ""))
            if len(calls) == 1:
                return {"final_trade_decision": _CONTRADICTORY_HOLD, "risk_debate_state": state["risk_debate_state"]}
            return {"final_trade_decision": _CONSISTENT_BUY, "risk_debate_state": state["risk_debate_state"]}
        return node

    wrapped_factory = make_consistent_portfolio_manager(fake_factory, lambda *a: None)
    node = wrapped_factory(llm=None)
    node({"risk_debate_state": {"history": "original debate"}})

    assert len(calls) == 2
    assert "REGRA DE PESO" in calls[1]  # not lost on the retry that appends the contradiction note


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
