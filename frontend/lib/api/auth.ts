import { authHeaders, request, type TokenPair } from "./client";

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
  email: string | null;
  nickname: string;
  is_guest: boolean;
  created_at: string;
}

export const authApi = {
  register: (payload: RegisterPayload, accessToken?: string) =>
    request<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      headers: accessToken ? authHeaders(accessToken) : undefined,
      body: JSON.stringify(payload),
    }),

  login: (email: string, password: string) =>
    request<TokenPair>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  guestLogin: () => request<TokenPair>("/api/v1/auth/guest", { method: "POST" }),

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
