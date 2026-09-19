import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CircleDollarSign } from 'lucide-react';
import './style.css';
import { LiveAnalysis } from './components/LiveAnalysis';
import { BacktestPanel } from './components/BacktestPanel';

type Tab = 'live' | 'backtest';

function App() {
  const [tab, setTab] = useState<Tab>('live');

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
        <button className={tab === 'live' ? 'active' : ''} onClick={() => setTab('live')}>Análise ao vivo</button>
        <button className={tab === 'backtest' ? 'active' : ''} onClick={() => setTab('backtest')}>Backtests</button>
      </nav>

      {tab === 'live' ? <LiveAnalysis /> : <BacktestPanel />}

      <footer><CircleDollarSign size={16} /> TradingAgentsGraph · Ollama <span>•</span> SOMENTE PAPEL</footer>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
