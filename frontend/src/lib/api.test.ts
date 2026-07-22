import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setUnauthorizedHandler } from './api'
import { jsonResponse } from '../test/utils'

describe('api wrapper', () => {
  it('GET sends only the CSRF header (no body or content-type) and returns parsed JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { hello: 'world' }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await api.get<{ hello: string }>('/api/v1/thing')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/thing', {
      method: 'GET',
      headers: { 'X-CSRF-Token': '1' },
      body: undefined,
    })
    expect(result).toEqual({ hello: 'world' })
  })

  it('POST with a body sets the JSON content-type and CSRF header and stringifies it', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { id: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/api/v1/users', { email: 'a@example.com' })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/users', {
      method: 'POST',
      headers: { 'X-CSRF-Token': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'a@example.com' }),
    })
  })

  it('POST without a body still sends the CSRF header and no body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/api/v1/auth/logout')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/logout', {
      method: 'POST',
      headers: { 'X-CSRF-Token': '1' },
      body: undefined,
    })
  })

  it('PATCH sends the body with the JSON content-type and CSRF header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { id: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.patch('/api/v1/users/1', { name: 'New' })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/users/1', {
      method: 'PATCH',
      headers: { 'X-CSRF-Token': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'New' }),
    })
  })

  it('resolves to undefined on 204', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(204, undefined)))
    const result = await api.del('/api/v1/users/1')
    expect(result).toBeUndefined()
  })

  it('upload sends the FormData without a JSON content-type', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { id: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    const data = new FormData()
    data.append('file', new File(['x'], 'a.png', { type: 'image/png' }))
    const result = await api.upload<{ id: number }>('/api/v1/profile/avatar', 'PUT', data)

    // Only the CSRF header, no Content-Type: the browser must set
    // multipart/form-data with its own boundary. A JSON Content-Type would break
    // the upload.
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/profile/avatar', {
      method: 'PUT',
      headers: { 'X-CSRF-Token': '1' },
      body: data,
    })
    const init = fetchMock.mock.calls[0][1]
    expect(init.headers).toEqual({ 'X-CSRF-Token': '1' })
    expect(result).toEqual({ id: 1 })
  })

  it('sends the X-CSRF-Token header on every method', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)

    await api.get('/api/v1/thing')
    await api.post('/api/v1/thing', { a: 1 })
    await api.patch('/api/v1/thing/1', { a: 1 })
    await api.del('/api/v1/thing/1')
    await api.upload('/api/v1/profile/avatar', 'POST', new FormData())

    for (const [, init] of fetchMock.mock.calls) {
      expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('1')
    }
  })

  it('throws ApiError with the detail from a JSON error body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(409, { detail: 'Taken' })))

    await expect(api.post('/api/v1/users', {})).rejects.toMatchObject({
      status: 409,
      message: 'Taken',
    })
  })

  it('falls back to statusText when the error body is not JSON', async () => {
    const notJson = {
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => {
        throw new Error('not json')
      },
    } as unknown as Response
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(notJson))

    await expect(api.get('/api/v1/thing')).rejects.toMatchObject({
      status: 500,
      message: 'Internal Server Error',
    })
  })

  it('ApiError is an Error carrying the status', () => {
    const err = new ApiError(403, 'Admin only')
    expect(err).toBeInstanceOf(Error)
    expect(err.status).toBe(403)
    expect(err.message).toBe('Admin only')
  })
})

describe('unauthorized signal', () => {
  // The handler is module-level state, so clear it after each case to stop it
  // leaking into the next test (or into other files).
  afterEach(() => setUnauthorizedHandler(null))

  it('invokes the registered handler on a 401 and still throws ApiError(401)', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'Expired' })))

    await expect(api.get('/api/v1/thing')).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('does not invoke the handler on non-401 errors (403, 500)', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(403, { detail: 'Admin only' })))
    await expect(api.get('/api/v1/thing')).rejects.toMatchObject({ status: 403 })

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(500, { detail: 'boom' })))
    await expect(api.get('/api/v1/thing')).rejects.toMatchObject({ status: 500 })

    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('invokes the handler when an upload gets a 401', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'Expired' })))

    await expect(api.upload('/api/v1/profile/avatar', 'PUT', new FormData())).rejects.toMatchObject(
      { status: 401 },
    )
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('stops invoking the handler once it is unregistered', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    setUnauthorizedHandler(null)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'Expired' })))

    await expect(api.get('/api/v1/thing')).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})
