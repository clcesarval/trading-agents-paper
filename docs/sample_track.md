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

## Nota sobre o 17/08: causa raiz investigada a fundo

Depois de mais correções (regra de peso catalisador-vs-risco, detector de
contradição Rating/plano de ação, detector de "catalisador confirmado
nomeado mas ignorado" — incluindo um bug de regex que não pegava o plural
"catalisadores confirmados"), o 17/08 foi re-testado 3 vezes adicionais:

- Numa execução, 1 de 3 tentativas saiu Buy (consenso 2/3) — a regra
  funcionou parcialmente.
- Na execução seguinte (com o bug do plural corrigido), voltou a 3/3 Hold —
  mas dessa vez **nenhuma das 3 tentativas sequer nomeou a descoberta como
  "catalisador"** no debate; a justificativa ficou genérica ("conflitos
  materiais sobre a sustentabilidade dos fundamentos"). Não há padrão de
  auto-contradição textual pra detectar quando o modelo simplesmente não
  engaja com o catalisador concreto.

**Conclusão**: existem pelo menos 3 causas distintas por trás de um Hold que
erra uma alta grande, e só uma delas é corrigível por regra de prompt/detector:
1. Informação genuinamente indisponível no momento da análise (2026-02-18) —
   não é bug, é incerteza real de mercado.
2. Auto-contradição textual explícita (nomeia o catalisador certo, escolhe o
   rating errado) — corrigível, e já tem detector com retry automático.
3. Raciocínio vago que evita nomear o catalisador concretamente e cai num
   "equilíbrio" genérico — não deixa rastro textual específico pra detectar
   sem arriscar falsos positivos; parece ser um limite de capacidade do
   modelo de 8B, não um bug de instrução.

## Experimento: qwen3:14b em vez de qwen3:8b (17/08)

Testado uma vez, com timeout aumentado para 3000s por tentativa: 2 das 3
execuções do consenso **estouraram o timeout** (>50min cada, mesmo com
retomada de checkpoint); só a 3ª completou (herdando o checkpoint das
anteriores). Resultado dessa única execução completa: **Overweight (Buy)**,
com o Investment Thesis aplicando a regra de peso corretamente pela primeira
vez de forma explícita — *"os catalisadores confirmados (datados e
concretos) superam os riscos estruturais (não novos), justificando uma
posição ligeiramente favorável (Overweight) em vez de Hold"*. Bateu com o
retorno real (+22,5%/+10,6%).

Confiança ficou baixa (55%) por um efeito colateral do timeout: retomar de
um checkpoint perde o rastro de evidências das etapas já concluídas no
processo anterior (que foi encerrado), então a auditoria de números/dados
falha mesmo que a decisão em si seja bem fundamentada.

**Conclusão**: há indício real de que um modelo maior aplica a regra de
peso catalisador-vs-risco melhor que o de 8B — mas o custo prático nessa
GPU (16GB) é alto demais pra usar como padrão: >50min por tentativa (vs.
~7min do 8b), a maioria das tentativas de consenso estourando o timeout, e
a auditoria de confiança degradada quando há retomada por timeout. Não
recomendado como padrão sem aumentar bastante o timeout e aceitar rodadas
de 1h+.

## Experimento: Mistral-Nemo 12B (família diferente, 7,5GB)

Testado com uma análise ao vivo (PETR4, smoke test de compatibilidade antes
de qualquer teste completo). Resultado: **rápido (4min12s**, vs. ~7min do
qwen3:8b), decisão extraída corretamente (Hold), números conferindo (65/65),
mas **4 de 9 etapas falharam em gerar saída estruturada** e caíram para
texto livre — incluindo a decisão final, que saiu como prosa corrida em vez
do formato `**Rating**: ... **Executive Summary**: ... **Investment
Thesis**: ...` que os detectores de contradição (`portfolio_forced.py`)
dependem para funcionar.

**Conclusão**: mais rápido não compensa aqui — os detectores de
contradição Rating/plano de ação e de catalisador ignorado simplesmente não
enxergam decisões em texto livre. Não recomendado como padrão sem antes
resolver a confiabilidade da saída estruturada (fora do escopo de um ajuste
de prompt).

**Teste específico no 17/08** (3 execuções de consenso, a data com resposta
real conhecida — Buy, +22,5%): saiu **Hold (2/3), com 1 tentativa em Sell**
(direção oposta à real). Nenhuma das 3 chegou a Buy — pior que o qwen3:8b
nesse caso específico. A 1ª tentativa até nomeou "há um catalisador datado e
confirmado (a tendência de alta)" e mesmo assim escolheu Hold — o mesmo
padrão de auto-contradição do qwen3:8b, só que em texto livre, então nosso
detector de catalisador ignorado nem consegue ler o Rating pra comparar.
Confirma: não é mais preciso, é só mais rápido e menos confiável.

## Experimento: Ministral 3 8B (geração mais nova da Mistral, dez/2025)

Diferente do Mistral-Nemo (modelo de 2024). Marketing oficial promete
"function calling nativo e saída JSON". Testado no 17/08 (3 execuções de
consenso, holding 20d): **Hold (2/3), Buy (1/3), confiança 83%**. Melhor que
o Mistral-Nemo (que tinha dado Sell numa tentativa), mas ainda sem maioria
Buy. Não cheguei a conferir se a saída ficou estruturada corretamente ou
se também caiu pra texto livre como o Mistral-Nemo — vale investigar antes
de descartar de vez.

## Experimento: Gemini (Google, via API paga/free tier) — bloqueado pela conta

Implementado suporte completo a provider alternativo no código (LLM_PROVIDER/
LLM_MODEL/GOOGLE_API_KEY, ver commit "Suporte a provider de LLM alternativo"),
pra testar Gemini 3.5 Flash-Lite (free tier do Google, com function
calling/JSON mode nativos). A chamada chegou certinho no Google (nome de
modelo correto, chave de API válida), mas a conta retornou **403
PERMISSION_DENIED** ("Your project has been denied access. Please contact
support") — a mesma restrição que já tinha bloqueado a criação da chave no
AI Studio ("Failed to create project: permission denied"). É uma restrição
do lado da conta Google (provavelmente precisa verificação), não do nosso
código ou do modelo. Revertido pro qwen3:8b local; o suporte a provider fica
pronto no código pra quando isso for resolvido.

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
