# Amostra de backtests — PETR4, com todas as correções ativas

Rastreamento manual de resultados reais, só de execuções feitas **depois** de
todas as correções desta rodada de investigação (temperature 0.2, consenso
entre execuções, correção de contradição do Portfolio Manager, memória de
decisões passadas ligada e com reflexão corrigida, regra de peso
catalisador-vs-risco). Holding padrão: 20 pregões, benchmark ^BVSP.

Objetivo: ver se, numa amostra maior (não só o 17/08), o sistema é
direcionalmente confiável quando se compromete com Buy/Sell, e se Hold
continua sendo o ponto fraco (perder altas/quedas grandes por cautela
excessiva) ou se, numa amostra maior, a maioria dos Holds é razoável
(movimentos pequenos, onde não fazer nada é a decisão certa mesmo).

## Amostra (12 datas)

| Data | Job ID | Decisão | Confiança | Retorno real (raw) | Alpha vs ^BVSP | Resolvido em | Avaliação |
|---|---|---|---|---|---|---|---|
| 2026-01-06 | 94759afa | Buy | 86% | +26,8% | +13,3% | 2026-02-03 | ✅ acertou |
| 2026-02-18 | e3df4559 | Hold | 100% | +26,4% | +29,8% | 2026-03-18 | ❌ perdeu alta grande |
| 2026-03-02 | db79daf7 | Buy | 91% | +20,8% | +24,4% | 2026-03-30 | ✅ acertou |
| 2026-03-16 | 06e32620 | Buy | 100% | +4,4% | -6,0% | 2026-04-14 | ~ ganhou em valor absoluto, perdeu do Ibovespa |
| 2026-04-13 | 7051eaad | Hold | 82% | -9,2% | +1,4% | 2026-05-13 | ~ defensável (mercado caiu) |
| 2026-05-01 | 1d6b8d70 | Sell | 93% | -14,1% | -6,9% | 2026-06-01 | ✅ acertou |
| 2026-06-09 | f0e42075 | Buy | 91% | -6,6% | -7,9% | 2026-07-07 | ❌ errou |
| 2026-06-22 | 7389536c | Hold | 93% | +5,1% | +3,3% | 2026-07-20 | ~ defensável (movimento pequeno) |
| 2026-07-06 | d55b9867 | Buy | 94% | +14,0% | +10,8% | 2026-08-03 | ✅ acertou |
| 2026-07-20 | 0b627325 | Hold | 93% | +3,2% | +7,0% | 2026-08-17 | ~ defensável |
| 2026-08-03 | a7084896 | Hold | 83% | +7,9% | +8,2% | 2026-08-31 | ~ limítrofe |
| 2026-08-17 | a0cf1b1f | Hold (consenso 3/3) | 94% | +22,5% | +10,6% | 2026-09-15 | ❌ perdeu alta |

## Resumo (n=12)

- **Chamadas direcionais (Buy/Sell): 6 no total** — 4 acertaram claramente
  (01/06, 03/02, 05/01, 07/06), 1 errou (06/09), 1 foi parcial (03/16: ganhou
  dinheiro em termos absolutos, mas perdeu do Ibovespa). ~75% de acerto.
- **Hold: 6 no total** — só 2 foram misses grandes (02/18: perdeu +26,4%/
  +29,8%; 17/08: perdeu +22,5%/+10,6%). As outras 4 (04/13, 06/22, 07/20,
  08/03) foram em movimentos pequenos a moderados (3% a 9%), onde não agir
  é uma decisão razoável, não um erro claro.
- **Revisão da conclusão anterior**: numa amostra maior, Hold não é
  sistematicamente ruim — a maioria dos Holds foi sobre movimentos modestos,
  exatamente o cenário em que Hold faz sentido. O problema real é mais
  estreito do que parecia: existem dois casos (02/18 e 17/08) em que um
  catalisador real e grande foi identificado no debate e mesmo assim o
  sistema escolheu Hold — isso é o padrão específico que vale investigar,
  não "Hold em geral".

Atualizar esta tabela conforme novas datas forem testadas.
