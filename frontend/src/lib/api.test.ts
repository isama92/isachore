import { describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import { jsonResponse } from '../test/utils'

describe('api wrapper', () => {
  it('GET sends no body or content-type and returns parsed JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { hello: 'world' }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await api.get<{ hello: string }>('/api/v1/thing')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/thing', {
      method: 'GET',
      headers: undefined,
      body: undefined,
    })
    expect(result).toEqual({ hello: 'world' })
  })

  it('POST with a body sets the JSON content-type and stringifies it', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { id: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/api/v1/users', { email: 'a@example.com' })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'a@example.com' }),
    })
  })

  it('POST without a body sends no headers or body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/api/v1/auth/logout')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/logout', {
      method: 'POST',
      headers: undefined,
      body: undefined,
    })
  })

  it('PATCH sends the body with the JSON content-type', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { id: 1 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.patch('/api/v1/users/1', { name: 'New' })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/users/1', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'New' }),
    })
  })

  it('resolves to undefined on 204', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(204, undefined)))
    const result = await api.del('/api/v1/users/1')
    expect(result).toBeUndefined()
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
