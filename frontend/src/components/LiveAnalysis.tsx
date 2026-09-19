import { useEffect, useRef, useState } from 'react';
import { Activity, Bot, ShieldCheck, TrendingUp } from 'lucide-react';
import { getJSON, postJSON } from '../api';
import { StatusBadge } from './StatusBadge';
import { RunLog } from './RunLog';

const AGENT_NAMES = ['Analista de Mercado', 'Analista Fundamentalista', 'Analista de Notícias', 'Pesquisador Otimista', 'Pesquisador Pessimista', 'Trader', 'Motor de Risco', 'Gestor de Portfólio'];

export function LiveAnalysis() {
  const [symbol, setSymbol] = useState('PETR4');
  const [result, setResult] = useState<any>(null);
  const [runStatus, setRunStatus] = useState('IDLE');
  const [logs, setLogs] = useState<any[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const hydratedOnce = useRef(false);

  const refreshLogs = () => getJSON('/api/analyze/logs').then(setLogs).catch(() => {});

  useEffect(() => {
    let cancelled = false;
    const sync = async () => {
      try {
        const state = await getJSON('/api/analyze/status');
        if (cancelled) return;
        setRunStatus(state.status || 'IDLE');
        if (state.symbol) setSymbol(state.symbol);
        if (state.status === 'RUNNING') {
          refreshLogs();
        } else if (state.result && !hydratedOnce.current) {
          // Reload-safe recovery: on first sync after mount, adopt whatever
          // the server already knows (last real decision, or ERROR) instead
          // of showing an empty "Pronto" screen after a page refresh.
          setResult(state.result);
          refreshLogs();
        }
        hydratedOnce.current = true;
      } catch {
        /* backend not reachable yet; keep polling */
      }
    };
    sync();
    const timer = window.setInterval(sync, 1000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const loading = runStatus === 'RUNNING';

  async function analyze() {
    if (loading) return;
    setNotice(null);
    setResult(null);
    setLogs([]);
    setRunStatus('RUNNING');
    const { ok, data } = await postJSON('/api/analyze', { symbol });
    if (!ok) {
      const detail = data.detail || data;
      setNotice(detail.message || 'Não foi possível iniciar a análise.');
      const state = await getJSON('/api/analyze/status').catch(() => null);
      setRunStatus(state?.status || 'IDLE');
      return;
    }
    setResult(data);
    setRunStatus(data.status || 'IDLE');
    refreshLogs();
  }

  const completed = runStatus === 'COMPLETED' && Boolean(result?.decision);
  const inconclusive = runStatus === 'INCONCLUSIVE';
  const failed = runStatus === 'ERROR';
  const agents = result?.agents?.length ? result.agents : AGENT_NAMES.map((name: string) => ({ name }));

  const title = failed
    ? `Falha em ${result?.symbol || symbol}`
    : inconclusive
      ? `${result?.symbol || symbol} · sem rating reconhecível`
      : completed
        ? `${result.symbol} · ${result.decision}`
        : 'Aguardando análise';

  return (
    <>
      <section className="search panel">
        <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} disabled={loading} />
        <button onClick={analyze} disabled={loading}>{loading ? 'ANALISANDO...' : 'ANALISAR ATIVO'}</button>
        <StatusBadge status={runStatus} />
        {notice && <small className="notice">{notice}</small>}
      </section>
      <section className="grid">
        <div className="panel chart">
          <div className="panelhead"><div><small>DECISÃO DA IA</small><h2>{title}</h2></div></div>
          <div className="chartbox">
            {failed ? (
              <div className="result-view">
                <strong className="decision sell">ERRO</strong>
                <span>{result?.error}</span>
                <small>Execução não concluída</small>
              </div>
            ) : inconclusive ? (
              <div className="result-view">
                <strong className="decision hold">INCONCLUSIVO</strong>
                <span>{result?.summary}</span>
                <small>O modelo não produziu um rating reconhecível — rode novamente, não é um HOLD real</small>
              </div>
            ) : completed ? (
              <div className="result-view">
                <strong className={`decision ${result.decision === 'BUY' ? 'buy' : result.decision === 'SELL' ? 'sell' : 'hold'}`}>{result.decision}</strong>
                {result.rating_5tier && <span className="rating5">{result.rating_5tier}</span>}
                <span>{result.summary}</span>
                <small>{result.provider} / {result.model} · execução {result.run_id}{result.market_data_confirmed === false ? ' · cotação própria indisponível (upstream buscou por conta própria)' : ''}</small>
              </div>
            ) : (
              <>
                <TrendingUp size={42} />
                <span>{loading ? 'A análise está em andamento' : 'Digite um ativo para iniciar o pipeline'}</span>
              </>
            )}
          </div>
        </div>
        <div className="panel">
          <div className="panelhead">
            <div><small>PIPELINE DE AGENTES</small><h2>{loading ? 'Executando...' : failed ? 'Execução com erro' : inconclusive ? 'Sem decisão reconhecível' : completed ? 'Análise concluída' : 'Sistema pronto'}</h2></div>
            <Bot />
          </div>
          {agents.map((agent: any, i: number) => (
            <div className="agent" key={agent.name}>
              <span className={i === agents.length - 1 ? 'shield' : ''}>{i === agents.length - 1 ? <ShieldCheck size={16} /> : <Activity size={16} />}</span>
              <b>{agent.name}</b>
              <label>{loading ? 'EXECUTANDO' : failed ? 'ERRO' : (completed || inconclusive) ? 'CONCLUÍDO' : 'NA FILA'}</label>
            </div>
          ))}
        </div>
      </section>
      <section className="panel logs">
        <div className="panelhead"><div><small>REGISTRO DE EXECUÇÃO AO VIVO</small><h2>{loading ? 'TradingAgents trabalhando...' : failed ? 'Execução encerrada com erro' : completed || inconclusive ? 'Última execução' : 'Eventos da última execução'}</h2></div></div>
        <RunLog logs={logs} emptyText="Os eventos aparecerão aqui durante a análise." />
      </section>
    </>
  );
}
