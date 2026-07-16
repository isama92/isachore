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

async function request<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return handle<T>(res)
}

// Multipart upload: let the browser set Content-Type (with the boundary), so
// this path deliberately does NOT set the JSON header the request() helper does.
async function upload<T>(path: string, method: string, data: FormData): Promise<T> {
  const res = await fetch(path, { method, body: data })
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
