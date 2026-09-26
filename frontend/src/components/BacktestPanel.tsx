import { useEffect, useState } from 'react';
import { getJSON, postJSON } from '../api';
import { formatDuration } from '../format';
import { StatusBadge } from './StatusBadge';
import { RunLog } from './RunLog';
import { ConfidenceBadge, ConfidenceDetail } from './Confidence';

function rowDuration(r: any): number | null {
  if (r.duration_seconds != null) return r.duration_seconds;
  // Still running: no finished_at yet, so show a live-ticking elapsed time
  // (refreshed every poll) instead of leaving the column blank until the
  // whole date finishes, which can take several minutes.
  if (r.status === 'RUNNING' && r.started_at) {
    return (Date.now() - new Date(r.started_at).getTime()) / 1000;
  }
  return null;
}

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
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

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
    setSelectedDate(null);
    setJob(data);
  }

  function cancel() {
    if (!job?.id) return;
    postJSON(`/api/backtest/${job.id}/cancel`, {});
  }

  async function retry() {
    if (!job?.id) return;
    setError(null);
    const { ok, data } = await postJSON(`/api/backtest/${job.id}/retry`, {});
    if (!ok) { setError(typeof data.detail === 'string' ? data.detail : 'Não foi possível reiniciar o backtest.'); return; }
    setSelectedDate(null);
    setJob(data);
  }

  async function redoDate(tradeDate: string, evt: any) {
    evt.stopPropagation(); // the row itself has its own onClick (select for log view)
    if (!job?.id) return;
    setError(null);
    const { ok, data } = await postJSON(`/api/backtest/${job.id}/redo/${tradeDate}`, {});
    if (!ok) { setError(typeof data.detail === 'string' ? data.detail : 'Não foi possível refazer essa data.'); return; }
    setJob(data);
  }

  const runs = job?.runs || [];
  const progress = job?.total_dates ? Math.min(100, Math.round((job.completed_dates / job.total_dates) * 100)) : 0;
  const jobActive = job && (job.status === 'QUEUED' || job.status === 'RUNNING');
  // Offered whenever some date still needs a real attempt — not only when the
  // job itself ended in ERROR/CANCELLED, since a job with a mix of completed
  // and errored dates still reports DONE overall (it did finish its range).
  const canRetry = job && !jobActive && (
    job.status === 'ERROR' || job.status === 'CANCELLED' || runs.some((r: any) => r.status === 'ERROR')
  );
  const totalElapsed = runs.reduce((sum: number, r: any) => sum + (rowDuration(r) || 0), 0);
  // Follows whichever date is running unless the user clicked an older one to inspect it.
  const activeDate = selectedDate || job?.current_date || (runs.length ? runs[runs.length - 1].trade_date : null);
  const selectedRun = runs.find((r: any) => r.trade_date === activeDate);
  const followingLive = jobActive && !selectedDate;

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
          <small>{job.completed_dates || 0} / {job.total_dates || 0} datas processadas{job.current_date ? ` · processando ${job.current_date}` : ''}{totalElapsed > 0 ? ` · ${formatDuration(totalElapsed)} de IA decorridos até agora` : ''}</small>
          {jobActive && <div><button className="link-button" onClick={cancel}>Cancelar agora (encerra a data em andamento imediatamente)</button></div>}
          {canRetry && (
            <div>
              <button className="link-button" onClick={retry}>Tentar novamente (só as datas pendentes)</button>
              {job.error && <small className="notice">{job.error}</small>}
            </div>
          )}

          <div className="chartbox backtest-chart"><EquityCurve runs={runs} /></div>

          <table className="results-table">
            <thead><tr><th>Data</th><th>Status</th><th>Rating</th><th>Retorno</th><th>Alpha</th><th>Resolvido em</th><th>Duração</th><th title="Quão bem fundamentada foi a leitura (dados, relatório, preços). Não é probabilidade de subir ou cair.">Confiança</th><th></th></tr></thead>
            <tbody>
              {runs.map((r: any) => (
                <tr key={r.id} className="job-row" onClick={() => setSelectedDate(r.trade_date)} style={r.trade_date === activeDate ? { background: '#0c1019' } : undefined}>
                  <td>{r.trade_date}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td>{r.rating_5tier || '—'}</td>
                  <td>{r.raw_return != null ? `${(r.raw_return * 100).toFixed(2)}%` : 'pendente'}</td>
                  <td className={r.alpha_return != null ? (r.alpha_return >= 0 ? 'positive' : 'negative') : ''}>{r.alpha_return != null ? `${(r.alpha_return * 100).toFixed(2)}%` : '—'}</td>
                  <td>{r.resolution_date || '—'}</td>
                  <td>{formatDuration(rowDuration(r))}</td>
                  <td><ConfidenceBadge pct={r.confidence_pct} detail={r.confidence_detail} /></td>
                  <td>
                    {!jobActive && (
                      <button className="link-button" onClick={(e) => redoDate(r.trade_date, e)} title="Roda essa data do zero, do primeiro agente ao último — não retoma de onde parou, então leva o mesmo tempo de uma análise nova (minutos, não segundos). Use quando o resultado atual não ajudou (ex.: INCONCLUSIVO) e você quer tentar de novo.">
                        Refazer
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {job && selectedRun && (
        <section className="panel logs">
          <div className="panelhead">
            <div>
              <small>REGISTRO DE EXECUÇÃO {followingLive ? '· AO VIVO' : ''}</small>
              <h2>Data {selectedRun.trade_date}{followingLive ? ' (acompanhando automaticamente)' : ''}</h2>
            </div>
            {!followingLive && jobActive && <button className="link-button" onClick={() => setSelectedDate(null)}>Voltar a acompanhar ao vivo</button>}
          </div>
          <p className="hint">Clique numa linha da tabela acima para ver os eventos daquela data específica.</p>
          <ConfidenceDetail pct={selectedRun.confidence_pct} detail={selectedRun.confidence_detail} />
          <RunLog logs={selectedRun.logs || []} emptyText="Sem eventos registrados para esta data ainda." />
        </section>
      )}

      <section className="panel">
        <div className="panelhead"><div><small>BACKTESTS ANTERIORES</small><h2>Histórico</h2></div></div>
        {jobs.length ? jobs.map((j) => (
          <div className="agent job-row" key={j.id} onClick={() => { setSelectedDate(null); getJSON(`/api/backtest/${j.id}`).then(setJob); }}>
            <b>{j.symbol}</b>
            <span>{j.start_date} → {j.end_date}</span>
            <label><StatusBadge status={j.status} /></label>
          </div>
        )) : <div className="emptylog">Nenhum backtest executado ainda.</div>}
      </section>
    </>
  );
}
