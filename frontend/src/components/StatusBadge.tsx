const LABELS: Record<string, string> = {
  IDLE: 'PRONTO',
  RUNNING: 'EXECUTANDO',
  COMPLETED: 'CONCLUÍDO',
  INCONCLUSIVE: 'INCONCLUSIVO',
  ERROR: 'ERRO',
  QUEUED: 'NA FILA',
  CANCELLED: 'CANCELADO',
  DONE: 'CONCLUÍDO',
};

export function StatusBadge({ status }: { status: string }) {
  const cls = `status-badge status-${(status || 'idle').toLowerCase()}`;
  return <span className={cls}>{LABELS[status] || status}</span>;
}
