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
import { authApi, type UserRead } from "./api-client";

interface AuthContextValue {
  accessToken: string | null;
  user: UserRead | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // The access token lives only in memory (spec 14-3: never localStorage),
    // so a page reload starts with none. Fall back to the refresh_token
    // cookie so a reload doesn't force a fresh login.
    let cancelled = false;

    authApi
      .refresh()
      .then(async (tokens) => {
        if (cancelled) return;
        setAccessToken(tokens.access_token);
        const me = await authApi.me(tokens.access_token);
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        // No valid refresh cookie - the visitor just isn't logged in yet.
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
    () => ({ accessToken, user, isLoading, login, logout }),
    [accessToken, user, isLoading, login, logout],
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
