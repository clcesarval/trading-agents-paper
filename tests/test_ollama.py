import pytest
from backend.app.llm.ollama import OllamaProvider


@pytest.mark.asyncio
async def test_health_check_unavailable():
    result = await OllamaProvider("http://127.0.0.1:1").health_check()
    assert result["available"] is False
