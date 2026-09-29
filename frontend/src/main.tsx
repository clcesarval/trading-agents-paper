import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CircleDollarSign } from 'lucide-react';
import './style.css';
import { getJSON } from './api';
import { LiveAnalysis } from './components/LiveAnalysis';
import { BacktestPanel } from './components/BacktestPanel';

type Tab = 'live' | 'backtest';

function App() {
  const [tab, setTab] = useState<Tab>('live');
  const [backtestRunning, setBacktestRunning] = useState(false);
  const [liveRunning, setLiveRunning] = useState(false);

  // Polled independently of which tab is open, so switching to "Análise ao
  // vivo" (or reloading the page) doesn't hide the fact that a backtest is
  // still chewing through dates in the background.
  useEffect(() => {
    const check = () => getJSON('/api/backtest')
      .then((jobs: any[]) => setBacktestRunning(jobs.some((j) => j.status === 'QUEUED' || j.status === 'RUNNING')))
      .catch(() => {});
    check();
    const timer = window.setInterval(check, 3000);
    return () => window.clearInterval(timer);
  }, []);

  // Same idea for a live analysis: visible from the Backtests tab too, so
  // switching away never hides that one is still running in the background.
  useEffect(() => {
    const check = () => getJSON('/api/analyze/status')
      .then((s: any) => setLiveRunning(s?.status === 'RUNNING'))
      .catch(() => {});
    check();
    const timer = window.setInterval(check, 3000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main>
      <header>
        <div>
          <span className="eyebrow">LABORATÓRIO DE TRADING COM IA / MODO PAPEL</span>
          <h1>Centro de comando do mercado</h1>
          <p>Monitor de execução em tempo real da TradingAgents.</p>
        </div>
        <div className="pill"><span />SOMENTE PAPEL</div>
      </header>

      <nav className="tabs">
        <button className={tab === 'live' ? 'active' : ''} onClick={() => setTab('live')}>
          Análise ao vivo
          {liveRunning && <span className="tab-live-dot" title="Uma análise ao vivo está em execução" />}
        </button>
        <button className={tab === 'backtest' ? 'active' : ''} onClick={() => setTab('backtest')}>
          Backtests
          {backtestRunning && <span className="tab-live-dot" title="Um backtest está em execução" />}
        </button>
      </nav>

      {tab === 'live' ? <LiveAnalysis /> : <BacktestPanel />}

      <footer><CircleDollarSign size={16} /> TradingAgentsGraph · Ollama <span>•</span> SOMENTE PAPEL</footer>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
