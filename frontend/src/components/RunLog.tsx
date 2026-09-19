import { useState } from 'react';

type LogEntry = { timestamp?: string; kind?: string; text?: string };

const TRUNCATE_AT = 240;

// Passe o mouse sobre o badge de cada evento para ver a explicação (title).
const KIND_INFO: Record<string, { label: string; hint: string }> = {
  run: { label: 'Execução', hint: 'Passo geral da execução (início, preparação, TradingAgentsGraph iniciado).' },
  graph: { label: 'Pipeline', hint: 'O grafo LangGraph com os agentes começou a rodar.' },
  config: { label: 'Config', hint: 'Aviso sobre como esta execução está configurada (ex.: quais analistas estão ativos e por quê).' },
  market: { label: 'Ticker', hint: 'Normalização do código do ativo (ex.: PETR4 → PETR4.SA).' },
  market_data: { label: 'Cotação', hint: 'Cotação de confirmação buscada pelo backend antes de chamar os agentes.' },
  market_error: { label: 'Cotação (falhou)', hint: 'A cotação de confirmação falhou; os agentes ainda tentam buscar dados por conta própria.' },
  external_request: { label: 'Fonte externa', hint: 'Tentativa de consultar uma fonte de cotação (Yahoo/Brapi/Alpha Vantage).' },
  external_response: { label: 'Fonte externa', hint: 'Resposta recebida da fonte de cotação.' },
  external_error: { label: 'Fonte externa (falhou)', hint: 'Essa fonte de cotação falhou; o app tenta a próxima.' },
  sentiment_request: { label: 'Sentimento', hint: 'Buscando dado real de sentimento (Reddit/StockTwits) antes de acionar a IA.' },
  sentiment_response: { label: 'Sentimento', hint: "Resultado da busca — leia o texto: dado real ou '<...unavailable>' (bloqueio da fonte, não é erro do app)." },
  ollama: { label: 'Ollama', hint: 'Status do modelo local: qual está carregado e quanta VRAM está usando.' },
  wait: { label: 'Aguardando', hint: 'Nenhum modelo ativo no momento; aguardando ferramenta ou dado de mercado.' },
  monitor: { label: 'Monitor', hint: 'Erro ao consultar o status do Ollama.' },
  tool_request: { label: 'Chamando ferramenta', hint: 'O agente de IA está chamando uma ferramenta de dados real (preço, notícia, fundamentos, etc.).' },
  tool_response: { label: 'Resposta da ferramenta', hint: 'O que a ferramenta devolveu para o agente — dado real, não inventado.' },
  tool_error: { label: 'Ferramenta (falhou)', hint: 'Essa chamada de ferramenta falhou.' },
  tool_end: { label: 'Ferramenta', hint: 'Resposta de uma ferramenta do LangGraph.' },
  tool: { label: 'Ferramenta', hint: 'Uma ferramenta foi acionada.' },
  agent_start: { label: 'Agente', hint: 'Um agente/etapa do pipeline começou.' },
  agent_end: { label: 'Agente', hint: 'Um agente/etapa do pipeline terminou.' },
  instrumentation: { label: 'Instrumentação', hint: 'Confirma quais módulos de ferramentas estão sendo monitorados nesta execução.' },
  error: { label: 'Erro', hint: 'Falha na execução.' },
  timeout: { label: 'Tempo esgotado', hint: 'A análise passou do tempo limite configurado e o processo foi encerrado.' },
  complete: { label: 'Concluído', hint: 'Decisão final ou encerramento da execução.' },
};

function kindInfo(kind?: string) {
  return KIND_INFO[kind || ''] || { label: kind || 'evento', hint: 'Evento da execução.' };
}

function LogLine({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const text = entry.text || '';
  const isLong = text.length > TRUNCATE_AT;
  const shown = expanded || !isLong ? text : `${text.slice(0, TRUNCATE_AT)}…`;
  const info = kindInfo(entry.kind);
  return (
    <div className={`log kind-${entry.kind || 'evento'}`}>
      <span>{entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : ''}</span>
      <b title={info.hint}>{info.label}</b>
      <em>
        {shown}
        {isLong && (
          <button className="log-more" onClick={() => setExpanded((v) => !v)}>
            {expanded ? 'mostrar menos' : 'mostrar mais'}
          </button>
        )}
      </em>
    </div>
  );
}

export function RunLog({ logs, emptyText }: { logs: LogEntry[]; emptyText: string }) {
  if (!logs.length) return <div className="emptylog">{emptyText}</div>;
  return (
    <>
      {logs.map((entry, i) => (
        <LogLine entry={entry} key={`${entry.timestamp}-${i}`} />
      ))}
    </>
  );
}
