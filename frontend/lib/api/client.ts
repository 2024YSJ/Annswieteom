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

async function throwIfError(res: Response): Promise<void> {
  if (res.ok) return;
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

export interface TokenPair {
  access_token: string;
  token_type: string;
}

// The access token lives in AuthProvider's React state (never localStorage —
// spec 14-3), but api-client is a plain module outside the component tree.
// AuthProvider registers itself here on mount so a silent refresh triggered
// from deep inside a request() call can push the new token back into React
// state, instead of every call site having to know about refreshing.
let onTokenRefreshed: ((token: string) => void) | null = null;

export function registerTokenRefreshHandler(handler: (token: string) => void) {
  onTokenRefreshed = handler;
}

const REFRESH_PATH = "/api/v1/auth/refresh";

/** One silent retry on 401: refresh the access token via the refresh_token
 * cookie and replay the original request with it. Skipped for the refresh
 * call itself (would recurse) and for requests that had no bearer token to
 * begin with (public endpoints legitimately returning 401, e.g. bad login).
 */
async function withAuthRetry(path: string, headers: HeadersInit | undefined, doFetch: (headers: HeadersInit | undefined) => Promise<Response>): Promise<Response> {
  const res = await doFetch(headers);
  const hadBearerToken = typeof headers === "object" && headers !== null && "Authorization" in headers;
  if (res.status !== 401 || path === REFRESH_PATH || !hadBearerToken) {
    return res;
  }

  const refreshRes = await fetch(`${API_BASE_URL}${REFRESH_PATH}`, { method: "POST", credentials: "include" });
  if (!refreshRes.ok) return res; // not logged in (anymore) - surface the original 401

  const { access_token } = (await refreshRes.json()) as TokenPair;
  onTokenRefreshed?.(access_token);
  return doFetch({ ...headers, Authorization: `Bearer ${access_token}` });
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await withAuthRetry(path, options.headers, (headers) =>
    fetch(`${API_BASE_URL}${path}`, {
      ...options,
      // Required so the browser sends/accepts the refresh_token cookie across
      // the frontend (Vercel) <-> backend (Railway) cross-site boundary.
      credentials: "include",
      headers: { "Content-Type": "application/json", ...headers },
    }),
  );

  await throwIfError(res);

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

/** For non-JSON responses (e.g. the plain-text export endpoint). */
export async function requestText(path: string, options: RequestInit = {}, accessToken?: string): Promise<string> {
  const headers = accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined;
  const res = await withAuthRetry(path, headers, (h) =>
    fetch(`${API_BASE_URL}${path}`, { ...options, credentials: "include", headers: { ...h, ...options.headers } }),
  );
  await throwIfError(res);
  return res.text();
}

/** multipart/form-data requests must NOT set Content-Type manually (the
 * browser needs to add its own boundary), so this bypasses `request()`. */
export async function requestForm<T>(path: string, formData: FormData, accessToken: string): Promise<T> {
  const res = await withAuthRetry(path, { Authorization: `Bearer ${accessToken}` }, (headers) =>
    fetch(`${API_BASE_URL}${path}`, { method: "POST", credentials: "include", headers, body: formData }),
  );
  await throwIfError(res);
  return (await res.json()) as T;
}

export function authHeaders(accessToken: string): HeadersInit {
  return { Authorization: `Bearer ${accessToken}` };
}
