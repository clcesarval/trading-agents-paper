export const API = 'http://localhost:8000';

export async function getJSON(path: string): Promise<any> {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
}

export async function postJSON(path: string, body: unknown): Promise<{ ok: boolean; status: number; data: any }> {
  const response = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, data };
}
