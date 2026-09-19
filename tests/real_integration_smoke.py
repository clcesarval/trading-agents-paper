import asyncio
from backend.app.agents.adapter import TradingAgentsAdapter
from backend.app.llm.ollama import OllamaProvider

async def main():
    result = await TradingAgentsAdapter(OllamaProvider("http://localhost:11434"), "qwen2.5:3b").analyze("PETR4")
    print(result["source"])
    print(result["decision"])
    print(result["summary"][:1000])

asyncio.run(main())
