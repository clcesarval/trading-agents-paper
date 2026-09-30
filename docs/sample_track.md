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

## Comparação direta: qwen3:8b vs. ministral-3:8b, mesmas 12 datas

Mesma metodologia, mesmas 12 datas, single-run (exceto 17/08 que usou
consenso 3x nos dois). Objetivo: já que o ministral-3 prometia function
calling nativo melhor, ver se isso se traduz em decisões melhores.

| Data | Retorno real | qwen3:8b | ministral-3:8b | Quem acertou |
|---|---|---|---|---|
| 2026-01-06 | +26,8%/+13,3% | Buy ✅ | Hold | qwen3:8b |
| 2026-02-18 | +26,4%/+29,8% | Hold (perdeu) | **Sell** (92%) | nenhum, mas ministral errou mais feio |
| 2026-03-02 | +20,8%/+24,4% | Buy ✅ | **Sell** (92%) | qwen3:8b |
| 2026-03-16 | +4,4%/-6,0% | Buy (parcial) | Sell (83%) | qwen3:8b |
| 2026-04-13 | -9,2%/+1,4% | Hold (defensável) | Sell (83%) | ministral, por sorte |
| 2026-05-01 | -14,1%/-6,9% | Sell ✅ | Hold | qwen3:8b |
| 2026-06-09 | -6,6%/-7,9% | Buy (errou) | Hold | ministral, por sorte |
| 2026-06-22 | +5,1%/+3,3% | Hold | Hold | empate |
| 2026-07-06 | +14,0%/+10,8% | Buy ✅ | Buy ✅ | empate (os dois acertaram) |
| 2026-07-20 | +3,2%/+7,0% | Hold | Hold | empate |
| 2026-08-03 | +7,9%/+8,2% | Hold | Sell (80%) | qwen3:8b |
| 2026-08-17 | +22,5%/+10,6% | Hold (consenso, perdeu) | Hold (consenso 2/3, perdeu) | nenhum |

**Conclusão: qwen3:8b continua sendo a melhor opção prática.** O ministral-3
mostrou um **viés forte e recorrente para Sell** — deu Sell com 80-92% de
confiança em 4 das 12 datas, e em 3 dessas 4 o preço **subiu forte** (+20%
a +26%). Isso é pior que "sempre Hold": errar a direção com confiança alta
é mais perigoso do que ficar neutro. Function calling nativo melhor não
compensou um julgamento de mercado pior nesse teste.

## Experimento: NVIDIA NIM (DeepSeek-V4.1-flash) — grátis, mas impraticável

Depois de Gemini (bloqueado pela conta) e Groq (limite de 6-8k tokens/min
menor que nosso contexto de 16k), NVIDIA NIM apareceu como a melhor opção
grátis no papel: ~40 req/min, contexto até 1,3M tokens, function calling
confirmado, e já estava registrado no código do projeto (só faltava a
chave). Implementado suporte genérico a chave de API por provider
(commit "Generaliza a propagacao de chave de API por provider").

Testado com uma análise ao vivo (PETR4, hoje) usando
`deepseek-ai/deepseek-v4.1-flash`. Resultado: **2 tentativas, ambas deram
timeout** — a 1ª aos 1500s (chegou a executar o Portfolio Manager, a
última etapa, mas não terminou a tempo); a 2ª, com timeout aumentado pra
2400s (40min) e supostamente retomando de checkpoint, **recomeçou do zero**
("checkpoint etapa 0" — nada de progresso real foi salvo) e também não
terminou em 40 minutos.

**Conclusão**: apesar das specs boas no papel, o modelo de "raciocínio" do
DeepSeek gera bastante texto de pensamento por chamada, e isso multiplicado
pela latência de rede ao longo de ~15-20 chamadas do pipeline (9 agentes +
debates) o torna **impraticavelmente lento** — pior que o qwen3:14b local,
que ao menos processava localmente sem latência de rede. Não é uma opção
viável pra esse projeto, mesmo sendo grátis. Suporte a NVIDIA como provider
fica no código (funciona, só não com esse modelo específico) — um modelo
NVIDIA menor/mais rápido (ex.: Nemotron) poderia ser testado depois, mas
sem prioridade por ora.

## Backtest grande: outubro/2025 inteiro (23 dias úteis, inédito)

Depois de decidir manter qwen3:8b como padrão, rodamos um intervalo real
inteiro (não datas escolhidas a dedo) pra ver o comportamento em volume:
PETR4, 01/10/2025 a 31/10/2025, holding 20 dias, single-run.

| Data | Decisão | Confiança | Retorno bruto | Alpha vs Ibovespa |
|---|---|---|---|---|
| 2025-10-01 | Hold | 89% | -4,3% | -6,5% |
| 2025-10-02 | Hold | 93% | -3,8% | -7,2% |
| 2025-10-03 | Hold | 98% | -4,0% | -7,7% |
| 2025-10-06 | Hold | 93% | -2,0% | -6,8% |
| 2025-10-07 | Hold | 99% | -1,9% | -8,5% |
| 2025-10-08 | Hold | 93% | +0,7% | -7,2% |
| 2025-10-09 | Hold | 87% | +2,6% | -5,6% |
| 2025-10-10 | *(sem rating — REVIEW)* | 85% | +7,5% | -2,0% |
| 2025-10-13 | Hold | 87% | +7,0% | -2,5% |
| 2025-10-14 | **Buy** | 93% | +10,6% | -0,7% |
| 2025-10-15 | Hold | 93% | +8,7% | -1,8% |
| 2025-10-16 | **Sell** | 91% | +10,3% | -0,2% |
| 2025-10-17 | Hold | 100% | +10,0% | +0,0% |
| 2025-10-20 | Hold | 100% | +10,5% | +1,9% |
| 2025-10-21 | **Buy** | 98% | +11,8% | +3,2% |
| 2025-10-22 | Hold | 90% | +9,9% | +2,7% |
| 2025-10-23 | Hold | 91% | +7,9% | +1,7% |
| 2025-10-24 | Hold | 86% | +9,0% | +2,8% |
| 2025-10-27 | Hold | 82% | +7,6% | +1,5% |
| 2025-10-28 | Hold | 98% | +7,5% | -0,1% |
| 2025-10-29 | **Buy** | 85% | +7,9% | +1,4% |
| 2025-10-30 | Hold | 87% | +6,4% | -0,6% |
| 2025-10-31 | Hold | 93% | +7,1% | +1,0% |

**Leitura honesta**: o retorno bruto sobe de forma dramática (-4% → +12%),
mas boa parte é o mercado como um todo subindo (Ibovespa também em alta),
não só a PETR4 — por isso o alpha (retorno menos o Ibovespa) é bem mais
moderado que o retorno bruto sugere.

Aplicando uma regra clara e consistente (Buy certo se alpha>0, Sell certo
se alpha<0, Hold certo se |alpha|<2%) em vez de só contar quantas vezes deu
Hold: **11 acertos, 11 erros, 1 não avaliável (REVIEW)** — bem mais
equilibrado do que "Hold em 17/23 dias" sugeria isoladamente. Os erros reais
se concentram em dois grupos: os primeiros 9 dias (alpha bem negativo, o
sistema devia ter sido mais cauteloso que um Hold simples) e dois dias no
meio da alta (22/10 e 24/10, quando devia ter mantido o Buy que tinha dado
em 21/10 em vez de voltar pro Hold).

**Achado mais concreto de instabilidade**: em 14/10 o sistema deu **Buy**
(correto), no dia seguinte (15/10) já tinha voltado pro **Hold**, e dois
dias depois (16/10) foi pro **Sell** — com o preço subindo o tempo todo
nesse trecho. Confirma, numa amostra grande e não escolhida a dedo, o
mesmo padrão de inconsistência dia-a-dia documentado no resto desse arquivo.

## Detector de reversão sem catalisador (3ª checagem do Portfolio Manager)

Motivado exatamente pelo achado acima (Buy 14/10 → Hold 15/10 → Sell 16/10
com o preço subindo o tempo todo), implementamos `detect_decision_reversal`
em `backend/app/execution/portfolio_forced.py`: compara a nova decisão do
Portfolio Manager com a última decisão anterior do mesmo ticker no
`TradingMemoryLog`. Se houver reversão direcional completa (Buy/Overweight
↔ Sell/Underweight) dentro de 5 dias corridos e sem catalisador
datado/confirmado citado no Investment Thesis, o Portfolio Manager é
re-invocado uma vez com uma nota de sistema pedindo revisão — mesmo padrão
"detectar e forçar retry" já usado nos outros dois checks (rating
contraditório e catalisador ignorado). Hold nunca é, por si só, tratado
como reversão (nem entrando nem saindo de Hold). 10 testes unitários novos
cobrem janela, cross-ticker, catalisador citado, ausência de histórico e o
retry do wrapper. Suíte completa: 131 passed. Commit `79ba74c`.

**Validação ao vivo**: reexecutamos PETR4 exatamente em 14–16/10/2025 (job
`bf051f34`) com o código novo já carregado no backend. O log de config
confirmou as três checagens ativas ("decisões com Rating contraditório ao
próprio plano de ação, a um catalisador que ele mesmo citou, ou a uma
reversão total sem fato novo recebem uma revisão automática"). Dessa vez,
com o modelo e os dados atuais, o resultado saiu **Hold nos três dias**
(-1,5%/-0,7%/+0,1% de alpha) — ou seja, o próprio flip-flop não se repetiu
organicamente nessa nova rodada, então o detector corretamente não teve
motivo para disparar (Hold→Hold nunca é reversão). Isso confirma que o
código está integrado e rodando sem erros/regressões, mas não é uma prova
ao vivo do disparo em si — essa parte já está coberta pelos testes
unitários com logs de memória sintéticos reproduzindo a reversão exata.
Provar o disparo ao vivo exigiria o modelo repetir a mesma reversão real,
o que não é controlável nem garantido.

## Caça a uma reversão real (noite de 29→30/09/2026): 78 dias, zero reversões

Depois da validação acima não pegar nenhuma reversão organicamente, rodamos
a noite toda em busca de uma ocorrência real: PETR4, holding 1 dia
(03–14/11/2025, job `6f128ba5`) e depois holding 20 dias — o padrão do
resto deste arquivo — num intervalo contínuo e inédito de 3 meses
(01/12/2025 a 28/02/2026, job `5a85e351`, 65 dias úteis).

**Resultado**: em **78 dias verificados no total**, o Portfolio Manager
nunca deu um único rating Sell/Underweight — só Hold, Buy e Overweight.
Sem nenhuma decisão bearish, a condição de reversão (virada completa
Bull↔Bear) nunca teve chance de ocorrer, e o detector de fato nunca
disparou nessa amostra. Isso não é uma falha do detector: é uma amostra
grande confirmando que, no comportamento atual do modelo, esse tipo de
flip-flop bearish (o caso de 14–16/10/2025 que motivou o detector) é raro,
não o padrão típico.

Tabela completa do intervalo de 3 meses (01/12/2025–28/02/2026, holding 20
dias, single-run):

| Data | Rating | Alpha (20d) | Data | Rating | Alpha (20d) |
|---|---|---|---|---|---|
| 2025-12-01 | Hold | -1,7% | 2026-01-16 | Hold | +2,0% |
| 2025-12-02 | Hold | -3,3% | 2026-01-19 | Hold | +2,8% |
| 2025-12-03 | Hold | -6,5% | 2026-01-20 | Hold | +3,7% |
| 2025-12-04 | Hold | -3,9% | 2026-01-21 | Hold | +2,7% |
| 2025-12-05 | Hold | -4,2% | 2026-01-22 | Hold | +7,4% |
| 2025-12-08 | Hold | -4,5% | 2026-01-23 | Hold | +5,9% |
| 2025-12-09 | Hold | -5,0% | 2026-01-26 | Buy | +4,9% |
| 2025-12-10 | Hold | -1,2% | 2026-01-27 | Hold | +4,6% |
| 2025-12-11 | Hold | +1,3% | 2026-01-28 | Buy | +3,1% |
| 2025-12-12 | Hold | +0,8% | 2026-01-29 | Overweight | +5,7% |
| 2025-12-15 | Hold | +2,8% | 2026-01-30 | Hold | +7,5% |
| 2025-12-16 | Hold | +4,0% | 2026-02-02 | Hold | +7,3% |
| 2025-12-17 | Hold | +1,5% | 2026-02-03 | Buy | +11,1% |
| 2025-12-18 | Hold | +2,8% | 2026-02-04 | Buy | +13,7% |
| 2025-12-19 | Hold | +0,9% | 2026-02-05 | Hold | +17,3% |
| 2025-12-22 | Hold | +3,1% | 2026-02-06 | Buy | +16,9% |
| 2025-12-23 | Hold | +5,3% | 2026-02-09 | Hold | +21,3% |
| 2025-12-24 | Hold | +5,7% | 2026-02-10 | Overweight | +24,1% |
| 2025-12-25 | Buy | +5,7% | 2026-02-11 | Overweight | +23,7% |
| 2025-12-26 | Hold | +5,7% | 2026-02-12 | Overweight | +27,8% |
| 2025-12-29 | Hold | +6,4% | 2026-02-13 | Overweight | +29,0% |
| 2025-12-30 | Hold | +8,7% | 2026-02-16 | Hold | +29,8% |
| 2025-12-31 | Hold | +10,0% | 2026-02-17 | Buy | +29,8% |
| 2026-01-01 | Hold | +10,0% | 2026-02-18 | Overweight | +29,8% |
| 2026-01-02 | Hold | +10,0% | 2026-02-19 | Hold | +28,1% |
| 2026-01-05 | Hold | +10,4% | 2026-02-20 | Hold | +27,8% |
| 2026-01-06 | Hold | +13,3% | 2026-02-23 | Hold | +22,9% |
| 2026-01-07 | Buy | +13,6% | 2026-02-24 | *(ERROR — timeout 1500s)* | — |
| 2026-01-08 | Hold | +10,7% | 2026-02-25 | Hold | +23,1% |
| 2026-01-09 | Hold | +9,0% | 2026-02-26 | Hold | +25,6% |
| 2026-01-12 | Hold | +8,8% | 2026-02-27 | Hold | +29,5% |
| 2026-01-13 | Hold | +5,2% | | | |
| 2026-01-14 | Hold | +4,2% | | | |
| 2026-01-15 | Hold | +3,3% | | | |

**Leitura honesta, aplicando a mesma regra do resto do arquivo** (Buy/
Overweight corretos se alpha>0; Hold correto se |alpha|<2%): dos 14 ratings
bullish (Buy/Overweight), **14 de 14 corretos** (o mercado realmente subiu
depois de cada um). Dos 50 Holds, só 7 ficaram dentro do limiar de 2% —
**43 foram misses** pela regra estrita.

Isso não significa que o modelo piorou: é o retrato de um mercado em alta
sustentada e sem grandes correções por 3 meses seguidos (o alpha de 20
dias sobe de forma quase monotônica de -1,7% em 01/12 até +29,8% em
meados de fevereiro). Num período assim, **qualquer Hold sustentado desde
o início da alta acumula um "erro" cada vez maior no horizonte de 20 dias**,
mesmo que a decisão individual, olhando só pra frente naquele dia, não
fosse claramente errada. O sistema levou de 01/12 até 26/01 (quase 2 meses)
pra reconhecer a tendência e começar a alternar entre Buy/Overweight e
Hold — nunca chegou a dar Sell nenhuma vez no trimestre inteiro. Isso é
consistente com o padrão já visto no backtest de outubro/2025: o sistema é
mais lento que o ideal para *entrar* numa tendência de alta, mas, uma vez
que entra, não fica dando flip-flop bearish sem motivo (daí zero disparos
do detector de reversão).

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
