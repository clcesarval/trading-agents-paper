# AI Trading Platform

Fase 1 de uma plataforma visual de AI Trading com paper trading. Nenhuma ordem real é suportada; `TRADING_MODE` deve ser `PAPER`.

## Rodar localmente

Backend: `python -m venv .venv`, `pip install -r backend/requirements.txt`, `python -m uvicorn backend.app.main:app --reload --port 8000`.

Frontend: `cd frontend`, `npm install`, `npm run dev`.

Ollama: instale/execute Ollama em `http://localhost:11434` e faça `ollama pull qwen3`. O endpoint `/api/health` detecta disponibilidade e `/api/llm/providers` lista modelos. A aplicação funciona sem Ollama, exibindo o estado indisponível.

Testes: `pytest -q`.

## Inicialização com um clique no Windows

Execute `start-trading.bat` com duplo clique. Ele prepara automaticamente o ambiente, instala dependências quando necessário, abre backend, frontend e navegador. Para encerrar, feche as duas janelas abertas.

Veja [ARCHITECTURE.md](ARCHITECTURE.md) para a análise do TradingAgents, decisões e roadmap.
