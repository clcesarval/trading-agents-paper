type LogEntry = { timestamp?: string; kind?: string; text?: string };

export function RunLog({ logs, emptyText }: { logs: LogEntry[]; emptyText: string }) {
  if (!logs.length) return <div className="emptylog">{emptyText}</div>;
  return (
    <>
      {logs.map((entry, i) => (
        <div className="log" key={`${entry.timestamp}-${i}`}>
          <span>{entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : ''}</span>
          <b>{entry.kind}</b>
          <em>{entry.text}</em>
        </div>
      ))}
    </>
  );
}
