export class ApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data: unknown = await res.json()
      if (data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string') {
        detail = data.detail
      }
    } catch {
      // response body was not JSON; keep the status text
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// Sent on every request so the backend CsrfProtectMiddleware accepts unsafe
// (POST/PATCH/PUT/DELETE) methods. The value is irrelevant: the defence is that
// a cross-site page cannot set a custom header without a blocked CORS preflight,
// so mere presence is enough. Safe methods ignore it server-side.
const CSRF_HEADER = 'X-CSRF-Token'

async function request<T>(path: string, method: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { [CSRF_HEADER]: '1' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return handle<T>(res)
}

// Multipart upload: pass only the CSRF header, NOT Content-Type, so the browser
// still sets multipart/form-data with its own boundary (the request() helper's
// JSON header would break the upload).
async function upload<T>(path: string, method: string, data: FormData): Promise<T> {
  const res = await fetch(path, { method, headers: { [CSRF_HEADER]: '1' }, body: data })
  return handle<T>(res)
}

export const api = {
  get: <T>(path: string) => request<T>(path, 'GET'),
  post: <T>(path: string, body?: unknown) => request<T>(path, 'POST', body),
  patch: <T>(path: string, body: unknown) => request<T>(path, 'PATCH', body),
  del: <T = undefined>(path: string) => request<T>(path, 'DELETE'),
  upload: <T>(path: string, method: 'PUT' | 'POST', data: FormData) =>
    upload<T>(path, method, data),
}
