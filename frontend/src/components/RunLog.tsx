import { useState } from 'react';

type LogEntry = { timestamp?: string; kind?: string; text?: string };

const TRUNCATE_AT = 240;

function LogLine({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const text = entry.text || '';
  const isLong = text.length > TRUNCATE_AT;
  const shown = expanded || !isLong ? text : `${text.slice(0, TRUNCATE_AT)}…`;
  return (
    <div className={`log kind-${entry.kind || 'evento'}`}>
      <span>{entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : ''}</span>
      <b>{entry.kind}</b>
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
