import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, Bot, CircleDollarSign, ShieldCheck, TrendingUp } from 'lucide-react';
import './style.css';

const names = ['Analista de Mercado', 'Analista Fundamentalista', 'Analista de Notícias', 'Debate Touro / Urso', 'Motor de Risco'];
const API = 'http://localhost:8000';

function App() {
  const [symbol, setSymbol] = useState('PETR4');
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [logs, setLogs] = useState<any[]>([]);
  const [runStatus, setRunStatus] = useState('IDLE');

  const refreshLogs = () => fetch(`${API}/api/analyze/logs`).then(r => r.json()).then(setLogs).catch(() => {});
  useEffect(() => {
    const sync = () => fetch(`${API}/api/analyze/status`).then(r => r.json()).then(state => {
      setRunStatus(state.status || 'IDLE');
      setLoading(state.status === 'RUNNING');
      if (state.symbol) setSymbol(state.symbol);
      if (state.status === 'RUNNING') refreshLogs();
    }).catch(() => {});
    sync();
    const timer = setInterval(sync, 1000);
    return () => clearInterval(timer);
  }, []);

  async function analyze() {
    if (loading) return;
    setLoading(true); setRunStatus('RUNNING'); setResult(null); setLogs([]);
    const timer = setInterval(refreshLogs, 700);
    try {
      const response = await fetch(`${API}/api/analyze`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({symbol})});
      const data = await response.json();
      if (!response.ok) {
        const detail = data.detail || data;
        setResult({status:detail.status || 'ERROR', symbol, error:detail.message || 'Não foi possível iniciar a análise.', run_id:detail.run_id});
        setRunStatus(detail.status || 'ERROR');
        return;
      }
      setResult(data); setRunStatus(data.status || 'COMPLETED');
    } catch (error) {
      setRunStatus('ERROR'); setResult({status:'ERROR', symbol, error:String(error)});
    } finally {
      clearInterval(timer); refreshLogs();
    }
  }

  const completed = runStatus === 'COMPLETED' && Boolean(result?.decision);
  const failed = result?.status === 'ERROR';
  const agents = result?.agents || names.map(name => ({name}));
  const title = failed ? `Falha em ${result.symbol || symbol}` : completed ? `${result.symbol} · ${result.decision}` : 'Aguardando análise';
  const statusText = loading ? 'Executando...' : completed ? 'Análise concluída' : failed ? 'Erro na análise' : runStatus === 'RUNNING' ? 'Análise já está em andamento' : 'Pronto';

  return <main>
    <header><div><span className="eyebrow">LABORATÓRIO DE TRADING COM IA / MODO PAPEL</span><h1>Centro de comando do mercado</h1><p>Monitor de execução em tempo real da TradingAgents.</p></div><div className="pill"><span/> SOMENTE PAPEL</div></header>
    <section className="search panel"><input value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())} disabled={loading}/><button onClick={analyze} disabled={loading}>{loading?'ANALISANDO...':'ANALISAR ATIVO'}</button><small>{statusText}</small></section>
    <section className="grid">
      <div className="panel chart"><div className="panelhead"><div><small>DECISÃO DA IA</small><h2>{title}</h2></div></div><div className="chartbox">{failed?<><strong className="decision">ERRO</strong><span>{result.error}</span><small>Execução não concluída</small></>:completed?<><strong className="decision">{result.decision}</strong><span>{result.summary}</span><small>{result.provider} / {result.model} · execução {result.run_id}</small></>:<><TrendingUp size={42}/><span>{loading?'A análise está em andamento':'Digite um ativo para iniciar o pipeline'}</span></>}</div></div>
      <div className="panel"><div className="panelhead"><div><small>PIPELINE DE AGENTES</small><h2>{loading?'Executando...':failed?'Execução com erro':completed?'Análise concluída':'Sistema pronto'}</h2></div><Bot/></div>{agents.map((x:any,i:number)=><div className="agent" key={x.name}><span className={i===4?'shield':''}>{i===4?<ShieldCheck size={16}/>:<Activity size={16}/>}</span><b>{x.name}</b><label>{loading?'EXECUTANDO':failed?'ERRO':completed?'CONCLUÍDO':i===0?'AGUARDANDO':'NA FILA'}</label></div>)}</div>
    </section>
    <section className="panel logs"><div className="panelhead"><div><small>REGISTRO DE EXECUÇÃO AO VIVO</small><h2>{loading?'TradingAgents trabalhando...':failed?'Execução encerrada com erro':completed?'Última execução concluída':'Eventos da última execução'}</h2></div></div>{logs.length?logs.map((l,i)=><div className="log" key={`${l.timestamp}-${i}`}><span>{new Date(l.timestamp).toLocaleTimeString()}</span><b>{l.kind}</b><em>{l.text}</em></div>):<div className="emptylog">Os eventos aparecerão aqui durante a análise.</div>}</section>
    <footer><CircleDollarSign size={16}/> TradingAgentsGraph · Ollama <span>•</span> SOMENTE PAPEL</footer>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App/>);
