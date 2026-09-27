# Amostra de backtests — PETR4, com todas as correções ativas

Rastreamento manual de resultados reais, só de execuções feitas **depois** de
todas as correções desta rodada de investigação (temperature 0.2, consenso
entre execuções, correção de contradição do Portfolio Manager, memória de
decisões passadas ligada e com reflexão corrigida, regra de peso
catalisador-vs-risco). Holding padrão: 20 pregões, benchmark ^BVSP.

Objetivo: ver se, numa amostra maior (não só o 17/08), o sistema é
direcionalmente confiável quando se compromete com Buy/Sell, e se Hold
continua sendo o ponto fraco (perder altas/quedas grandes por cautela
excessiva).

## Amostra

| Data | Job ID | Decisão | Confiança | Retorno real (raw) | Alpha vs ^BVSP | Resolvido em | Avaliação |
|---|---|---|---|---|---|---|---|
| 2026-08-17 | a0cf1b1f | Hold (consenso 3/3) | 94% | +22,5% | +10,6% | 2026-09-15 | ❌ perdeu alta |
| 2026-07-06 | d55b9867 | Buy | 94% | +14,0% | +10,8% | 2026-08-03 | ✅ acertou |
| 2026-01-06 | 94759afa | Buy | 86% | +26,8% | +13,3% | 2026-02-03 | ✅ acertou |
| 2026-02-18 | e3df4559 | Hold | 100% | +26,4% | +29,8% | 2026-03-18 | ❌ perdeu alta grande |
| 2026-04-13 | 7051eaad | Hold | 82% | -9,2% | +1,4% | 2026-05-13 | ~ defensável |
| 2026-05-01 | 1d6b8d70 | Sell | 93% | -14,1% | -6,9% | 2026-06-01 | ✅ acertou |
| 2026-06-09 | f0e42075 | Buy | 91% | -6,6% | -7,9% | 2026-07-07 | ❌ errou |

## Resumo (n=7)

- **Chamadas direcionais (Buy/Sell): 3 de 4 acertaram (75%)**.
- **Hold: 1 de 3 claramente defensável**; as outras duas perderam altas de
  +22,5% e +26,4%/+29,8%.
- Padrão consistente: quando o sistema se compromete com uma direção, tende
  a acertar; quando escolhe Hold, é onde mais perde altas reais.

Atualizar esta tabela conforme novas datas forem testadas.
