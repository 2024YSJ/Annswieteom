"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { authApi, registerTokenRefreshHandler, type UserRead } from "./api-client";

interface AuthContextValue {
  accessToken: string | null;
  user: UserRead | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  guestLogin: () => Promise<string>;
  refreshUser: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Lets api-client push a silently-refreshed token back into this state
    // (401 -> refresh -> retry, spec 14-3), without every call site needing
    // to know about the refresh flow.
    registerTokenRefreshHandler(setAccessToken);
  }, []);

  useEffect(() => {
    // The access token lives only in memory (spec 14-3: never localStorage),
    // so a page reload starts with none. Fall back to the refresh_token
    // cookie so a reload doesn't force a fresh login.
    let cancelled = false;

    // `fetch` has no default timeout — if the request stalls (a network/proxy
    // that silently drops the connection instead of erroring, rather than a
    // clean failure or a slow-but-eventually-answering cold start) the
    // promise never settles, and with no button on screen yet, the visitor
    // is stuck on the loading screen with no way to escape it. Racing against
    // a timeout guarantees isLoading always resolves, so at worst a stalled
    // check degrades to the normal logged-out view (still fully usable —
    // login/register/guest are separate requests) instead of a dead end.
    //
    // This must stay above Render free-tier's real cold-start ceiling
    // (LoadingNotice documents "최대 1분") — a shorter timeout here doesn't
    // just show the logged-out view sooner, it actively misclassifies a
    // visitor who WAS already logged in (valid refresh cookie) as logged out
    // the moment the backend happens to be cold. On the homepage that visitor
    // then sees the guest-start button and can end up creating a second,
    // disconnected guest account/session instead of resuming their first one
    // — this was a live production bug (2026-09-05) traced back to this
    // timeout being set to 15s while a cold start can take up to a minute.
    const AUTH_CHECK_TIMEOUT_MS = 65000;
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("auth_check_timeout")), AUTH_CHECK_TIMEOUT_MS),
    );

    Promise.race([authApi.refresh(), timeout])
      .then(async (tokens) => {
        if (cancelled) return;
        setAccessToken(tokens.access_token);
        const me = await authApi.me(tokens.access_token);
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        // No valid refresh cookie, or the check timed out - either way the
        // visitor just isn't logged in (yet).
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await authApi.login(email, password);
    setAccessToken(tokens.access_token);
    const me = await authApi.me(tokens.access_token);
    setUser(me);
  }, []);

  const guestLogin = useCallback(async () => {
    const tokens = await authApi.guestLogin();
    setAccessToken(tokens.access_token);
    const me = await authApi.me(tokens.access_token);
    setUser(me);
    return tokens.access_token;
  }, []);

  // Re-fetches /auth/me with the *current* access token, without issuing a
  // new one. Used right after a guest "upgrades" via /auth/register — the
  // access token only ever encodes user_id, so the same row's now-registered
  // data (email, is_guest=false) shows up without needing to log in again.
  const refreshUser = useCallback(async () => {
    if (!accessToken) return;
    const me = await authApi.me(accessToken);
    setUser(me);
  }, [accessToken]);

  const logout = useCallback(async () => {
    if (accessToken) {
      await authApi.logout(accessToken).catch(() => {
        // best-effort: still clear local state even if the request failed
      });
    }
    setAccessToken(null);
    setUser(null);
  }, [accessToken]);

  const value = useMemo(
    () => ({ accessToken, user, isLoading, login, guestLogin, refreshUser, logout }),
    [accessToken, user, isLoading, login, guestLogin, refreshUser, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
