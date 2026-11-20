const TOKEN_KEY = "ta_token";
export const SESIJA_ISTEKLA = "ta:sesija-istekla";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, { ...options, headers });
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    clearToken();
    window.dispatchEvent(new Event(SESIJA_ISTEKLA));
    throw new Error("Sesija je istekla. Prijavite se ponovo.");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Greška" }));
    throw new Error(err.detail || "Greška");
  }
  return res.json() as Promise<T>;
}
