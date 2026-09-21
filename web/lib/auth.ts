import { API_URL } from "./api";

const TOKEN_KEY = "eb-token";

export type Me = { username: string; role: string };

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode */
  }
}

export class AuthError extends Error {}

/** fetch with the bearer token attached, and a typed error on failure. */
export async function authed<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  });

  if (res.status === 401) {
    setToken(null);
    throw new AuthError("Session expired — please sign in again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(typeof detail === "string" ? detail : res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function login(
  username: string,
  password: string
): Promise<string> {
  // /auth/login takes form encoding, not JSON.
  const body = new URLSearchParams({ username, password });
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (res.status === 401) throw new Error("Wrong username or password.");
  if (!res.ok) throw new Error(`Sign-in failed (${res.status}).`);
  const { access_token } = await res.json();
  setToken(access_token);
  return access_token;
}

export async function register(
  username: string,
  password: string
): Promise<{ api_key: string }> {
  const res = await fetch(`${API_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    let detail: unknown = "Registration failed.";
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* keep default */
    }
    throw new Error(readableDetail(detail, "Registration failed."));
  }
  return res.json();
}

/* A validation error arrives as a list of {loc, msg}; the person wants
   the sentence, not "Unprocessable Entity". */
function readableDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean)
      .map((m) => m.replace(/^Value error, |^String should /, (s) => (s.startsWith("String") ? "Password should " : "")));
    if (msgs.length) return msgs.join(" · ");
  }
  return fallback;
}

export function me(): Promise<Me> {
  return authed<Me>("/auth/me");
}

/* Sign out means signed out: the server bumps the account's session
   version, so this token — and any other minted before now — is refused
   from here on. The local copy goes regardless of whether the server
   could be reached. */
export async function logout(): Promise<void> {
  const token = getToken();
  setToken(null);
  if (!token) return;
  try {
    await fetch(`${API_URL}/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    /* offline: the local token is gone, and the server's version will
       catch the token the next time it is seen */
  }
}
