import pytest
from backend.app.market_data.providers import MarketDataProviderChain


class FakeProvider:
    def __init__(self, name, outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0

    async def get_quote(self, symbol):
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return {**outcome, "symbol": symbol.upper()}


@pytest.mark.asyncio
async def test_falls_back_to_second_provider_when_first_fails():
    first = FakeProvider("first", [RuntimeError("indisponível"), RuntimeError("indisponível")])
    second = FakeProvider("second", [{"price": 10.5, "currency": "BRL"}])
    chain = MarketDataProviderChain(first, second)
    events = []
    result = await chain.get_quote("PETR4", events.append)
    assert result["price"] == 10.5
    assert result["provider"] == "FakeProvider"
    assert first.calls == 2
    assert any(e["kind"] == "external_error" for e in events)


@pytest.mark.asyncio
async def test_retries_same_provider_before_falling_back():
    flaky = FakeProvider("flaky", [RuntimeError("timeout transiente"), {"price": 42.0, "currency": "BRL"}])
    unused = FakeProvider("unused", [{"price": 1.0}])
    chain = MarketDataProviderChain(flaky, unused)
    result = await chain.get_quote("PETR4")
    assert result["price"] == 42.0
    assert flaky.calls == 2
    assert unused.calls == 0


@pytest.mark.asyncio
async def test_raises_with_aggregated_errors_when_all_providers_fail():
    first = FakeProvider("first", [RuntimeError("erro-a")])
    second = FakeProvider("second", [RuntimeError("erro-b")])
    chain = MarketDataProviderChain(first, second)
    with pytest.raises(RuntimeError) as excinfo:
        await chain.get_quote("PETR4")
    assert "erro-a" in str(excinfo.value)
    assert "erro-b" in str(excinfo.value)
