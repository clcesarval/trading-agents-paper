# TradingAgents Paper — plataforma de análise multi-agente (paper trading)

Plataforma local que roda o pipeline multi-agente do [TradingAgents](https://github.com/TauricResearch/TradingAgents)
(vendorizado em `tradingagents_upstream/`) contra um modelo Ollama local, para
**analisar** ações da B3 e reportar uma **confiança honesta** na leitura —
não uma recomendação de compra/venda. **Só paper trading.** Nenhuma ordem
real é executada; `TRADING_MODE` deve ser sempre `PAPER`.

## O que o app faz

- **Análise ao vivo**: roda os 9 agentes (Mercado, Sentimento, Notícias,
  Fundamentalista, debate Bull/Bear, Research Manager, Trader, debate de
  risco, Portfolio Manager) para uma ação da B3, hoje.
- **Backtest histórico**: reexecuta o pipeline completo para cada dia de um
  intervalo passado e calcula o retorno real (preço) e o alpha contra o
  Ibovespa (`^BVSP`) depois que o período de holding se resolve. Não é
  instantâneo — cada data custa o mesmo tempo de uma análise ao vivo.
- **Consenso entre execuções**: uma mesma data pode rodar N vezes (1 a 5); a
  decisão final só é reportada quando há maioria estrita entre as tentativas,
  em vez de confiar numa única rodada.

## Confiança na leitura, não recomendação

O núcleo do projeto é um sistema de **confiança objetiva** (`backend/app/analysis/confidence.py`):
uma nota 0–100% que mede o quanto a análise está fundamentada em dados
verificáveis — nunca a probabilidade de a ação subir ou cair. Ela cobre:

- **Indicadores calculados por código**, não pelo modelo (`market_forced.py`)
  — o Analista de Mercado só escreve texto sobre números que uma função
  determinística já calculou e verificou.
- **Auditoria de números** (`analysis/numbers.py`): todo número que aparece
  no texto de cada agente é comparado com o que as ferramentas de dados
  realmente retornaram (preços, indicadores, balanço, notícias). Números sem
  fonte são listados, não escondidos.
- **Preços absurdos derrubam a nota**: um stop-loss ou alvo muito distante do
  fechamento real limita a confiança a 60%, mesmo que o resto da análise
  esteja bem escrito.
- **Frescor de dados**: o último balanço é avaliado pelo próprio ciclo
  (trimestral vs. anual), não por um prazo fixo.
- **Concordância entre etapas**: se Research Manager, Trader e Portfolio
  Manager divergem de direção, isso pesa contra a confiança.

## Correções de confiabilidade (a decisão em si)

Além de medir a confiança, o projeto endereça bugs reais encontrados ao
investigar por que a mesma data podia sair com decisões diferentes em
execuções distintas:

- **Temperature de amostragem controlada** (`llm_temperature`, padrão 0.2) —
  reduz o ruído puro de amostragem, que pesquisa sobre o próprio
  TradingAgents mediu como responsável por boa parte da instabilidade.
- **Portfolio Manager auto-consistente** (`execution/portfolio_forced.py`) —
  detecta quando o *Rating* escolhido contradiz o próprio plano de ação
  (ex.: "Rating: Hold" ao lado de "posicione-se comprando...") e pede uma
  revisão automática antes de aceitar a decisão.
- **Regra de peso catalisador vs. risco genérico** — instrui o debate a não
  tratar risco estrutural permanente (dívida, volatilidade de commodity)
  como equivalente a um catalisador datado e confirmado (uma notícia real
  com data).
- **Memória de decisões passadas** (Fase B) — o upstream já registra toda
  decisão e já lê "lições de decisões anteriores" no prompt do Portfolio
  Manager, mas nada preenchia o resultado real depois que o retorno ficava
  conhecido. Isso foi ligado (`analysis/memory_feedback.py`), incluindo a
  correção de um prompt de reflexão que tratava um Hold que perdeu uma alta
  real como "decisão correta".

Essas correções são gerais (aplicam a qualquer ticker/data), nunca ajustadas
para acertar um caso específico — ver `docs/sample_track.md` para o
acompanhamento honesto de acerto/erro numa amostra de datas reais.

## Rodar localmente

Backend: `python -m venv .venv`, `pip install -r backend/requirements.txt`,
`python -m uvicorn backend.app.main:app --reload --port 8000`.

Frontend: `cd frontend`, `npm install`, `npm run dev`.

Ollama: instale/execute em `http://localhost:11434` e baixe um modelo com
"thinking" (recomendado: `ollama pull qwen3:8b`, com
`OLLAMA_CONTEXT_LENGTH=16384` — o contexto padrão de 4k trunca os prompts
maiores desse pipeline). `/api/health` detecta disponibilidade; o app
funciona sem Ollama, mostrando o estado indisponível.

A análise roda num processo isolado (`multiprocessing`), com timeout
configurável via `ANALYSIS_TIMEOUT_SECONDS` (padrão 1500s / 25min) — reflete
o tempo real de 9 agentes num modelo local, não um timeout curto. Estado e
histórico ficam em SQLite (`DATABASE_URL`, padrão `data/trading.db`).

Testes: `pytest -q` (mais de 100 testes cobrindo confiança, auditoria de
números, consenso, memória e as correções acima).

## Inicialização com um clique no Windows

Execute `start-trading.bat` com duplo clique. Prepara o ambiente, instala
dependências quando necessário, abre backend, frontend e navegador. Para
encerrar, feche as janelas abertas.

## Documentação

- [ARCHITECTURE.md](ARCHITECTURE.md) — análise do TradingAgents, decisões de
  design e roadmap.
- [docs/sample_track.md](docs/sample_track.md) — acompanhamento honesto de
  quantas decisões bateram com o retorno real numa amostra de datas.
