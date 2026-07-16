import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import Chores from './Chores'
import { jsonResponse, mockFetch, renderWithProviders } from '../test/utils'
import { makeChore, makeTag, makeUser } from '../test/fixtures'

const me = makeUser({ id: 1, name: 'Alex' })

describe('Chores', () => {
  it('lists chores with assignees, tags and labels', async () => {
    const chore = makeChore({
      id: 7,
      title: 'Scrub the tub',
      assignees: [makeUser({ id: 2, name: 'Jo' })],
      tags: [makeTag({ id: 3, name: 'deep-clean', color: '#0d9488' })],
      repeats: 'daily',
      assignment_type: 'least_done',
    })
    mockFetch([{ path: '/api/v1/chores', method: 'GET', body: [chore] }])
    renderWithProviders(<Chores />, { authValue: { user: me } })

    expect(await screen.findByText('Scrub the tub')).toBeInTheDocument()
    expect(screen.getByText('Jo')).toBeInTheDocument()
    expect(screen.getByText('deep-clean')).toBeInTheDocument()
    expect(screen.getByText('Daily')).toBeInTheDocument()
    expect(screen.getByText('Least done')).toBeInTheDocument()
  })

  it('shows placeholders for an unassigned, untagged chore', async () => {
    mockFetch([{ path: '/api/v1/chores', method: 'GET', body: [makeChore({ title: 'Lonely' })] }])
    renderWithProviders(<Chores />, { authValue: { user: me } })

    expect(await screen.findByText('Lonely')).toBeInTheDocument()
    expect(screen.getByText('Unassigned')).toBeInTheDocument()
    expect(screen.getByText('None')).toBeInTheDocument()
  })

  it('shows an empty state when there are no chores', async () => {
    mockFetch([{ path: '/api/v1/chores', method: 'GET', body: [] }])
    renderWithProviders(<Chores />, { authValue: { user: me } })

    expect(await screen.findByText('No chores yet.')).toBeInTheDocument()
  })

  it('deletes a chore after confirming in the dialog and reloads', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const toastSpy = vi.spyOn(toast, 'success')
    let deleted = false
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString()
      const method = (init?.method ?? 'GET').toUpperCase()
      if (url.endsWith('/api/v1/chores/7') && method === 'DELETE') {
        deleted = true
        return jsonResponse(204, undefined)
      }
      return jsonResponse(200, deleted ? [] : [makeChore({ id: 7, title: 'Scrub the tub' })])
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWithProviders(<Chores />, { authValue: { user: me } })
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete chore' }),
    )

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/chores/7',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    )
    expect(await screen.findByText('No chores yet.')).toBeInTheDocument()
    expect(toastSpy).toHaveBeenCalledWith('Chore deleted')
  })

  it('does not delete when the dialog is cancelled', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const fetchMock = mockFetch([
      {
        path: '/api/v1/chores',
        method: 'GET',
        body: [makeChore({ id: 7, title: 'Scrub the tub' })],
      },
    ])
    renderWithProviders(<Chores />, { authValue: { user: me } })
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }),
    )

    expect(fetchMock).not.toHaveBeenCalledWith(
      '/api/v1/chores/7',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('shows an error when loading fails', async () => {
    mockFetch([{ path: '/api/v1/chores', method: 'GET', status: 500, body: { detail: 'boom' } }])
    renderWithProviders(<Chores />, { authValue: { user: me } })

    expect(await screen.findByText('boom')).toBeInTheDocument()
  })
})
