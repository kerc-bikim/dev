export type Me = { username: string; role: string };
export type Health = { ok: boolean; db: boolean; redis: boolean };
export type WizardQuestion = { key: string; question: string; options: string[] };
export type WizardMatch = {
  instconfig: string;
  description: string;
  parameters: Record<string, string>;
};
export type WizardResult = {
  element: string;
  manufacturer: string;
  model: string;
  answers: Record<string, string>;
  questions: WizardQuestion[];
  locked: Record<string, string>;
  matches: WizardMatch[];
  match_count: number;
};

export async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* ignore */
  }
  return `요청 실패 (${response.status})`;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
}

export const apiGet = api;

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiText(path: string): Promise<string> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) throw new Error(await readError(response));
  return response.text();
}
