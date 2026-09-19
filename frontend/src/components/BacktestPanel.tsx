import { useEffect, useState } from 'react';
import { getJSON, postJSON } from '../api';
import { StatusBadge } from './StatusBadge';

function EquityCurve({ runs }: { runs: any[] }) {
  const points = runs.filter((r) => r.alpha_return != null);
  if (!points.length) {
    return <div className="emptylog">Ainda sem retornos calculados (aguardando dados de preço para as datas concluídas).</div>;
  }
  const width = 560, height = 160, pad = 24;
  let cumulative = 0;
  const series = points.map((r) => (cumulative += r.alpha_return));
  const min = Math.min(0, ...series);
  const max = Math.max(0, ...series);
  const range = max - min || 1;
  const stepX = (width - pad * 2) / Math.max(1, series.length - 1);
  const toY = (v: number) => height - pad - ((v - min) / range) * (height - pad * 2);
  const path = series.map((v, i) => `${i === 0 ? 'M' : 'L'} ${pad + i * stepX} ${toY(v)}`).join(' ');
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Curva de alpha acumulado do backtest">
      <line x1={pad} y1={toY(0)} x2={width - pad} y2={toY(0)} stroke="#263246" strokeDasharray="4 4" />
      <path d={path} fill="none" stroke="#57e890" strokeWidth={2} />
      {series.map((v, i) => (
        <circle key={i} cx={pad + i * stepX} cy={toY(v)} r={3} fill={v >= 0 ? '#57e890' : '#e2586b'} />
      ))}
    </svg>
  );
}

export function BacktestPanel() {
  const [symbol, setSymbol] = useState('PETR4');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [holdingDays, setHoldingDays] = useState(5);
  const [job, setJob] = useState<any>(null);
  const [jobs, setJobs] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadJobs = () => getJSON('/api/backtest').then(setJobs).catch(() => {});
  useEffect(() => { loadJobs(); }, []);

  useEffect(() => {
    if (!job?.id) return;
    const active = job.status === 'QUEUED' || job.status === 'RUNNING';
    if (!active) return;
    const timer = window.setInterval(async () => {
      try {
        const fresh = await getJSON(`/api/backtest/${job.id}`);
        setJob(fresh);
        if (fresh.status !== 'QUEUED' && fresh.status !== 'RUNNING') loadJobs();
      } catch { /* transient poll failure, try again next tick */ }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status]);

  async function start() {
    setError(null);
    if (!startDate || !endDate) { setError('Informe as datas de início e fim.'); return; }
    const { ok, data } = await postJSON('/api/backtest', { symbol, start_date: startDate, end_date: endDate, holding_days: holdingDays });
    if (!ok) { setError(typeof data.detail === 'string' ? data.detail : 'Não foi possível iniciar o backtest.'); return; }
    setJob(data);
  }

  function cancel() {
    if (!job?.id) return;
    postJSON(`/api/backtest/${job.id}/cancel`, {});
  }

  const runs = job?.runs || [];
  const progress = job?.total_dates ? Math.min(100, Math.round((job.completed_dates / job.total_dates) * 100)) : 0;
  const jobActive = job && (job.status === 'QUEUED' || job.status === 'RUNNING');

  return (
    <>
      <section className="panel search backtest-form">
        <div className="field"><label>Ativo</label><input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} disabled={jobActive} /></div>
        <div className="field"><label>Início</label><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} disabled={jobActive} /></div>
        <div className="field"><label>Fim</label><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} disabled={jobActive} /></div>
        <div className="field"><label>Holding (dias)</label><input type="number" min={1} max={60} value={holdingDays} onChange={(e) => setHoldingDays(Number(e.target.value))} disabled={jobActive} /></div>
        <button onClick={start} disabled={jobActive}>{jobActive ? 'RODANDO...' : 'RODAR BACKTEST'}</button>
        {error && <small className="notice">{error}</small>}
      </section>
      <p className="hint">Cada data reexecuta o pipeline completo de agentes — o mesmo tempo de uma análise ao vivo. Um backtest de 10 dias pode levar dezenas de minutos numa GPU de 4GB; acompanhe pelo progresso abaixo, não é instantâneo.</p>

      {job && (
        <section className="panel">
          <div className="panelhead">
            <div><small>BACKTEST {job.symbol}</small><h2>{job.start_date} → {job.end_date}</h2></div>
            <StatusBadge status={job.status} />
          </div>
          <div className="progress"><div className="progress-fill" style={{ width: `${progress}%` }} /></div>
          <small>{job.completed_dates || 0} / {job.total_dates || 0} datas processadas{job.current_date ? ` · processando ${job.current_date}` : ''}</small>
          {jobActive && <div><button className="link-button" onClick={cancel}>Cancelar após a data atual</button></div>}

          <div className="chartbox backtest-chart"><EquityCurve runs={runs} /></div>

          <table className="results-table">
            <thead><tr><th>Data</th><th>Status</th><th>Rating</th><th>Retorno</th><th>Alpha</th><th>Resolvido em</th></tr></thead>
            <tbody>
              {runs.map((r: any) => (
                <tr key={r.id}>
                  <td>{r.trade_date}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td>{r.rating_5tier || '—'}</td>
                  <td>{r.raw_return != null ? `${(r.raw_return * 100).toFixed(2)}%` : 'pendente'}</td>
                  <td className={r.alpha_return != null ? (r.alpha_return >= 0 ? 'positive' : 'negative') : ''}>{r.alpha_return != null ? `${(r.alpha_return * 100).toFixed(2)}%` : '—'}</td>
                  <td>{r.resolution_date || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="panel">
        <div className="panelhead"><div><small>BACKTESTS ANTERIORES</small><h2>Histórico</h2></div></div>
        {jobs.length ? jobs.map((j) => (
          <div className="agent job-row" key={j.id} onClick={() => getJSON(`/api/backtest/${j.id}`).then(setJob)}>
            <b>{j.symbol}</b>
            <span>{j.start_date} → {j.end_date}</span>
            <label><StatusBadge status={j.status} /></label>
          </div>
        )) : <div className="emptylog">Nenhum backtest executado ainda.</div>}
      </section>
    </>
  );
}
