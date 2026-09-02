const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    // Required so the browser sends/accepts the refresh_token cookie across
    // the frontend (Vercel) <-> backend (Railway) cross-site boundary.
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // no JSON body to read the detail from
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export interface TokenPair {
  access_token: string;
  token_type: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  nickname: string;
}

export interface RegisterResponse {
  user_id: string;
}

export interface UserRead {
  id: string;
  email: string;
  nickname: string;
  created_at: string;
}

export const authApi = {
  register: (payload: RegisterPayload) =>
    request<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  login: (email: string, password: string) =>
    request<TokenPair>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  refresh: () => request<TokenPair>("/api/v1/auth/refresh", { method: "POST" }),

  logout: (accessToken: string) =>
    request<void>("/api/v1/auth/logout", {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    }),

  me: (accessToken: string) =>
    request<UserRead>("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${accessToken}` },
    }),
};
