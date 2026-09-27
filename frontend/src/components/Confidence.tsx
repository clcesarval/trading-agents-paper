type Check = { id: string; label: string; weight: number; score: number | null; status: string; reason: string; items?: string[] };
type Consensus = { runs: number; votes: Record<string, number>; decision: string | null; agreement: number; confidence_pct: number | null; note: string };
export type ConfidenceDetailData = { pct: number | null; label: string | null; coverage?: number; cap?: { limit: number; reason: string } | null; checks: Check[]; caveat: string; consensus?: Consensus } | null | undefined;

function ConsensusBlock({ consensus }: { consensus: Consensus }) {
  const hasConsensus = consensus.decision != null;
  return (
    <div className="conf-caveat" style={{ borderTop: 0, paddingTop: 0, margin: '0 0 10px', color: hasConsensus ? '#57e890' : '#e2586b' }}>
      <b>{hasConsensus ? 'Consenso entre execuções' : 'Sem consenso entre execuções'}</b>: {consensus.note}
      {' '}<span style={{ opacity: 0.8 }}>({Object.entries(consensus.votes).map(([label, count]) => `${label}: ${count}`).join(' · ')})</span>
    </div>
  );
}

const MARK: Record<string, string> = { ok: '✓', parcial: '~', falhou: '✗', 'n/a': '–' };

function tone(pct: number | null | undefined) {
  if (pct == null) return 'conf-none';
  return pct >= 75 ? 'conf-high' : pct >= 50 ? 'conf-mid' : 'conf-low';
}

export function ConfidenceBadge({ pct, detail }: { pct: number | null | undefined; detail?: ConfidenceDetailData }) {
  if (pct == null) return <span className="conf-badge conf-none" title="Ainda não calculada para esta execução">—</span>;
  const problems = (detail?.checks || []).filter((c) => c.status === 'falhou' || c.status === 'parcial').map((c) => `${c.label}: ${c.reason}`);
  const partial = detail?.coverage != null && detail.coverage < 100 ? `Avaliação parcial (${detail.coverage}% dos critérios). ` : '';
  const title = `${detail?.label ? `Confiança ${detail.label}. ` : ''}${partial}${problems.length ? `Pontos de atenção: ${problems.join(' | ')}` : 'Nenhum ponto de atenção.'}`;
  return <span className={`conf-badge ${tone(pct)}`} title={title}>{pct}%</span>;
}

export function ConfidenceDetail({ pct, detail }: { pct: number | null | undefined; detail: ConfidenceDetailData }) {
  // A "sem consenso" date has no single reading to score (pct is null on
  // purpose — averaging confidences across disagreeing decisions would
  // invent a number) but still has a consensus block worth showing, so only
  // the complete absence of a detail object hides the panel.
  if (!detail) return null;
  return (
    <div className="conf-panel">
      <div className="conf-head">
        <small>CONFIANÇA NA LEITURA</small>
        <div className="conf-score">
          <strong className={tone(pct)}>{pct != null ? `${pct}%` : '—'}</strong>
          {detail.label && <span className={`conf-badge ${tone(pct)}`}>{detail.label}</span>}
        </div>
      </div>
      {detail.consensus && <ConsensusBlock consensus={detail.consensus} />}
      {detail.cap && (
        <p className="conf-caveat" style={{ borderTop: 0, paddingTop: 0, margin: '0 0 10px', color: '#e2586b' }}>
          Nota limitada a {detail.cap.limit}%: {detail.cap.reason}
        </p>
      )}
      {detail.coverage != null && detail.coverage < 100 && (
        <p className="conf-caveat" style={{ borderTop: 0, paddingTop: 0, margin: '0 0 10px' }}>
          Avaliação parcial: só {detail.coverage}% dos critérios puderam ser conferidos nesta execução.
        </p>
      )}
      <ul className="conf-checks">
        {detail.checks.map((c) => (
          <li key={c.id} className={`conf-check st-${c.status.replace('/', '')}`}>
            <span className="conf-mark">{MARK[c.status] || '·'}</span>
            <div>
              <b>{c.label}</b><em>{c.reason}</em>
              {c.items && c.items.length > 0 && (
                <ul className="conf-items">{c.items.map((it, i) => <li key={i}>{it}</li>)}</ul>
              )}
            </div>
          </li>
        ))}
      </ul>
      <p className="conf-caveat">{detail.caveat}</p>
    </div>
  );
}
