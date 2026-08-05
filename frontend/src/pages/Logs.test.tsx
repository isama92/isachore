import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Logs from './Logs'
import { membershipsFor, ownedMemberships, renderWithProviders } from '../test/utils'
import { makeHouseholdMember, makeLogEntry, makeUser } from '../test/fixtures'
import type { HistoryFilterOptions, LogEntry } from '../lib/types'

const me = makeHouseholdMember({ id: 1, first_name: 'Alex', last_name: 'Kim' })
const jo = makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })
const authUser = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

type FetchMock = ReturnType<typeof vi.fn>

function jsonBody(data: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => data,
  } as Response
}

function stubFetch(opts: {
  entries: LogEntry[]
  options?: HistoryFilterOptions
  status?: number
}): FetchMock {
  const options = opts.options ?? {
    households: [{ id: 1, name: 'Test Household', timezone: 'UTC' }],
    members: [me],
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input).split('?')[0]
    if (path.endsWith('/api/v1/completions/filters')) return jsonBody(options)
    if (path.endsWith('/api/v1/logs')) {
      if (opts.status && opts.status >= 400) return jsonBody({ detail: 'boom' }, opts.status)
      return jsonBody({ items: opts.entries, total: opts.entries.length, page: 1, page_size: 10 })
    }
    return jsonBody(undefined, 204)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastLogsGet(fetchMock: FetchMock): string {
  const calls = fetchMock.mock.calls.filter(([url]) =>
    String(url).split('?')[0].endsWith('/api/v1/logs'),
  )
  return String(calls.at(-1)?.[0] ?? '')
}

// Owner of household 1, which is where makeLogEntry puts its rows.
const asOwner = { authValue: { user: authUser, memberships: ownedMemberships(1) } }

describe('Logs', () => {
  it('lists an entry with its household, actor, action and chore', async () => {
    stubFetch({
      entries: [
        makeLogEntry({
          id: 7,
          action: 'chore_deleted',
          chore_title: 'Scrub the tub',
          household: { id: 1, name: 'Beach House', timezone: 'UTC' },
          actor: jo,
        }),
      ],
    })
    renderWithProviders(<Logs />, asOwner)

    const row = (await screen.findByText('Scrub the tub')).closest('tr')!
    expect(within(row).getByText('Beach House')).toBeInTheDocument()
    expect(within(row).getByText('Jo Ng')).toBeInTheDocument()
    expect(within(row).getByText('Chore deleted')).toBeInTheDocument()
  })

  it('names whose closure an undo erased', async () => {
    // Without this the row reads "Alex Kim / Completion undone / Bins" and never says whose
    // work went, which is the fact the log exists to record - and the reason
    // completion_undone and skip_undone are two actions rather than one flagged one.
    stubFetch({
      entries: [
        makeLogEntry({
          action: 'completion_undone',
          chore_title: 'Bins',
          actor: me,
          target: jo,
        }),
      ],
    })
    renderWithProviders(<Logs />, asOwner)

    const row = (await screen.findByText('Bins')).closest('tr')!
    expect(within(row).getByText('Completion undone')).toBeInTheDocument()
    expect(within(row).getByText('recorded by Jo Ng')).toBeInTheDocument()
    // The actor is still the person who pressed undo, not the person named in the suffix.
    expect(within(row).getByText('Alex Kim')).toBeInTheDocument()
  })

  it('adds no such suffix to an action that has no target', async () => {
    // Three of the five actions carry no target, which is why this is a suffix and not a
    // column - and the assertion that keeps the suffix from rendering an empty phrase.
    stubFetch({
      entries: [makeLogEntry({ action: 'chore_deleted', chore_title: 'Bins', target: null })],
    })
    renderWithProviders(<Logs />, asOwner)

    const row = (await screen.findByText('Bins')).closest('tr')!
    expect(within(row).getByText('Chore deleted')).toBeInTheDocument()
    expect(within(row).queryByText(/recorded by/)).not.toBeInTheDocument()
  })

  it('names the changed fields of an update', async () => {
    stubFetch({
      entries: [
        makeLogEntry({
          action: 'chore_updated',
          chore_title: 'Bins',
          changed_fields: ['title', 'repeat_interval'],
        }),
      ],
    })
    renderWithProviders(<Logs />, asOwner)

    const row = (await screen.findByText('Bins')).closest('tr')!
    expect(within(row).getByText('Title, Repeat every')).toBeInTheDocument()
  })

  it('falls back to the raw name for a field it does not know', async () => {
    // A newer server writing a field an older client is reading. The known name alongside it
    // proves the row rendered at all rather than collapsing.
    stubFetch({
      entries: [
        makeLogEntry({
          action: 'chore_updated',
          chore_title: 'Bins',
          changed_fields: ['title', 'nickname_colour'],
        }),
      ],
    })
    renderWithProviders(<Logs />, asOwner)

    const row = (await screen.findByText('Bins')).closest('tr')!
    expect(within(row).getByText('Title, nickname colour')).toBeInTheDocument()
  })

  it('renders an unknown action readably rather than as a translation key', async () => {
    // Reachable for real: the API sends `action` as a plain string precisely so a row written
    // by a newer release cannot break the read, so this is the shape that arrives - not a
    // hypothetical. Coercing it back through the enum server-side would 500 the whole page.
    stubFetch({ entries: [makeLogEntry({ action: 'chore_archived', chore_title: 'Bins' })] })
    renderWithProviders(<Logs />, asOwner)

    const row = (await screen.findByText('Bins')).closest('tr')!
    expect(within(row).getByText('chore archived')).toBeInTheDocument()
    expect(screen.queryByText(/logs\.actions/)).not.toBeInTheDocument()
  })

  it('shows a placeholder in the changes column when no fields moved', async () => {
    stubFetch({
      entries: [makeLogEntry({ action: 'chore_created', chore_title: 'Bins', changed_fields: [] })],
    })
    renderWithProviders(<Logs />, asOwner)

    const row = (await screen.findByText('Bins')).closest('tr')!
    expect(within(row).getByText('—')).toBeInTheDocument()
  })

  it('shows a placeholder when the actor is unknown', async () => {
    stubFetch({ entries: [makeLogEntry({ chore_title: 'Bins', actor: null })] })
    renderWithProviders(<Logs />, asOwner)

    const row = (await screen.findByText('Bins')).closest('tr')!
    expect(within(row).getByText('Unknown')).toBeInTheDocument()
  })

  it('marks an action taken through an admin session without naming the operator', async () => {
    stubFetch({ entries: [makeLogEntry({ chore_title: 'Bins', actor: jo, by_admin: true })] })
    renderWithProviders(<Logs />, asOwner)

    const row = (await screen.findByText('Bins')).closest('tr')!
    expect(within(row).getByText('Jo Ng')).toBeInTheDocument()
    expect(within(row).getByText('(via admin)')).toBeInTheDocument()
  })

  it('asks for the newest first', async () => {
    const fetchMock = stubFetch({ entries: [makeLogEntry({ chore_title: 'Bins' })] })
    renderWithProviders(<Logs />, asOwner)

    await screen.findByText('Bins')
    expect(lastLogsGet(fetchMock)).toContain('sort_by=created_at')
    expect(lastLogsGet(fetchMock)).toContain('sort_dir=desc')
  })

  it('sorts by When and by nothing else', async () => {
    // A column id IS the server's sort key, and only created_at is whitelisted, so a sortable
    // header anywhere else would push a key the endpoint 422s.
    stubFetch({ entries: [makeLogEntry({ chore_title: 'Bins' })] })
    renderWithProviders(<Logs />, asOwner)

    await screen.findByText('Bins')
    expect(screen.getByRole('button', { name: 'When' })).toBeInTheDocument()
    for (const header of ['Household', 'Who', 'What', 'Chore', 'Changed']) {
      expect(screen.queryByRole('button', { name: header })).not.toBeInTheDocument()
    }
  })

  it('filters by action and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({ entries: [makeLogEntry({ chore_title: 'Bins' })] })
    renderWithProviders(<Logs />, asOwner)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Bins')
    await user.click(screen.getByRole('combobox', { name: 'Action' }))
    await user.click(await screen.findByRole('option', { name: 'Chore deleted' }))

    await waitFor(() => expect(lastLogsGet(fetchMock)).toContain('action=chore_deleted'))
  })

  it('filters by the person who acted and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({
      entries: [makeLogEntry({ chore_title: 'Bins' })],
      options: {
        households: [{ id: 1, name: 'Test Household', timezone: 'UTC' }],
        members: [me, jo],
      },
    })
    renderWithProviders(<Logs />, asOwner)
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Bins')
    await user.click(await screen.findByRole('combobox', { name: 'Changed by' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))

    await waitFor(() => expect(lastLogsGet(fetchMock)).toContain('user_id=2'))
  })

  it('filters by household and pushes the choice into the query', async () => {
    const fetchMock = stubFetch({
      entries: [makeLogEntry({ chore_title: 'Bins' })],
      options: {
        households: [
          { id: 1, name: 'Flat 3B', timezone: 'UTC' },
          { id: 2, name: 'Beach House', timezone: 'UTC' },
        ],
        members: [me],
      },
    })
    renderWithProviders(<Logs />, {
      authValue: { user: authUser, memberships: ownedMemberships(1, 2) },
    })
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByText('Bins')
    await user.click(await screen.findByRole('combobox', { name: 'Household' }))
    await user.click(await screen.findByRole('option', { name: 'Beach House' }))

    await waitFor(() => expect(lastLogsGet(fetchMock)).toContain('household_id=2'))
  })

  it('offers only the households the user owns', async () => {
    // The load-bearing negative for "owner is not organiser": the payload lists two, and the
    // caller merely organises the second. Below two owned households the Select is hidden.
    const fetchMock = stubFetch({
      entries: [makeLogEntry({ chore_title: 'Bins' })],
      options: {
        households: [
          { id: 1, name: 'Flat 3B', timezone: 'UTC' },
          { id: 2, name: 'Beach House', timezone: 'UTC' },
        ],
        members: [me],
      },
    })
    renderWithProviders(<Logs />, {
      authValue: {
        user: authUser,
        memberships: [...ownedMemberships(1), ...membershipsFor('organiser', 2)],
      },
    })

    await screen.findByText('Bins')
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    // The positive half: the options really loaded, so the missing Select is the narrowing
    // rather than a fixture that never answered.
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/completions/filters'))).toBe(
      true,
    )
  })

  it('keeps the action filter when there is nothing else to choose between', async () => {
    // One member, one owned household: both option-driven Selects are hidden, and Action is
    // not - it is a closed list of ours, so no payload can empty it.
    stubFetch({ entries: [makeLogEntry({ chore_title: 'Bins' })] })
    renderWithProviders(<Logs />, asOwner)

    await screen.findByText('Bins')
    expect(screen.queryByRole('combobox', { name: 'Changed by' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Action' })).toBeInTheDocument()
  })

  it('forgets a remembered household filter it no longer owns', async () => {
    // A household transferred away. Below two owned households the Select is hidden, so
    // nothing on screen could clear it and the page would stay empty forever.
    localStorage.setItem(
      'isachore-table-logs',
      JSON.stringify({
        pageSize: 10,
        sortBy: 'created_at',
        sortDir: 'desc',
        filters: { household_id: '99', user_id: '', action: '' },
      }),
    )
    const fetchMock = stubFetch({ entries: [makeLogEntry({ chore_title: 'Bins' })] })
    renderWithProviders(<Logs />, asOwner)

    await waitFor(() => {
      // The prefix assertion first: `lastLogsGet` returns '' before any request has landed,
      // which would satisfy the negative below for the wrong reason.
      expect(lastLogsGet(fetchMock)).toContain('/api/v1/logs?')
      expect(lastLogsGet(fetchMock)).not.toContain('household_id')
    })
  })

  it('forgets a remembered action the app no longer knows', async () => {
    localStorage.setItem(
      'isachore-table-logs',
      JSON.stringify({
        pageSize: 10,
        sortBy: 'created_at',
        sortDir: 'desc',
        filters: { household_id: '', user_id: '', action: 'chore_archived' },
      }),
    )
    const fetchMock = stubFetch({ entries: [makeLogEntry({ chore_title: 'Bins' })] })
    renderWithProviders(<Logs />, asOwner)

    await waitFor(() => {
      expect(lastLogsGet(fetchMock)).toContain('/api/v1/logs?')
      expect(lastLogsGet(fetchMock)).not.toContain('action')
    })
  })

  it('shows an empty state when nothing has been logged', async () => {
    stubFetch({ entries: [] })
    renderWithProviders(<Logs />, asOwner)

    expect(await screen.findByText('Nothing logged yet.')).toBeInTheDocument()
  })

  it('shows an error when loading fails', async () => {
    stubFetch({ entries: [], status: 500 })
    renderWithProviders(<Logs />, asOwner)

    expect(await screen.findByText('Failed to load the log')).toBeInTheDocument()
  })
})
