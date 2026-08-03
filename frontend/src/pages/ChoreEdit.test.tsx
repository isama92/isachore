import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import ChoreEdit from './ChoreEdit'
import { membershipsFor, mockFetch, renderWithProviders } from '../test/utils'
import { makeChore, makeHouseholdMember, makeTag, makeUser } from '../test/fixtures'
import type { Page } from '../lib/types'

// jsdom cannot drive a contenteditable, so the rich text editor is swapped for a textarea with
// the same contract. See src/test/richTextEditorMock.tsx for why, and
// src/components/rich-text/RichTextEditor.test.tsx for the real editor's own coverage.
vi.mock('@/components/rich-text/RichTextEditor', () => import('../test/richTextEditorMock'))

const me = makeUser({ id: 1, first_name: 'Alex', last_name: 'Kim' })

const MEMBERS = /\/api\/v1\/households\/\d+\/members/
const TAGS = /\/api\/v1\/tags(\?|$)/

function page<T>(items: T[]): Page<T> {
  return { items, total: items.length, page: 1, page_size: 100 }
}

function patchBody(mock: ReturnType<typeof mockFetch>): Record<string, unknown> {
  const call = mock.mock.calls.find(([, init]) => init?.method === 'PATCH')
  if (!call) throw new Error('no PATCH call recorded')
  return JSON.parse(String(call[1]?.body)) as Record<string, unknown>
}

const savedChore = makeChore({
  id: 7,
  title: 'Scrub the tub',
  description: 'Old notes',
  household: { id: 4, name: 'Beach House' },
  assignees: [makeUser({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
  tags: [makeTag({ id: 3, name: 'deep-clean' })],
})

function editMocks(overrides: { patchStatus?: number; patchBody?: unknown } = {}) {
  return mockFetch([
    { path: '/api/v1/chores/7', method: 'GET', body: savedChore },
    {
      path: MEMBERS,
      method: 'GET',
      body: page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]),
    },
    { path: TAGS, method: 'GET', body: page([makeTag({ id: 3, name: 'deep-clean' })]) },
    {
      path: '/api/v1/chores/7',
      method: 'PATCH',
      status: overrides.patchStatus ?? 200,
      body: overrides.patchBody ?? savedChore,
    },
  ])
}

function renderEdit() {
  return renderWithProviders(
    <Routes>
      <Route path="/chores/:id/edit" element={<ChoreEdit />} />
      <Route path="/chores" element={<div>chores-list</div>} />
    </Routes>,
    // The saved chore belongs to household 4, and ChoreEdit leaves for the list unless the
    // caller organises *that* household - the route guard only proves they organise somewhere.
    {
      authValue: { user: me, memberships: membershipsFor('organiser', 4) },
      route: '/chores/7/edit',
    },
  )
}

describe('ChoreEdit', () => {
  it('pre-fills the form and shows the household read-only', async () => {
    editMocks()
    renderEdit()

    expect(await screen.findByDisplayValue('Scrub the tub')).toBeInTheDocument()
    // The household is shown but is not an editable control.
    expect(screen.getByText('Beach House')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Household' })).not.toBeInTheDocument()
    // Its assignee is pre-selected (shown as a badge on the picker trigger).
    expect(
      within(screen.getByRole('button', { name: 'Assignees' })).getByText('Jo Ng'),
    ).toBeInTheDocument()
  })

  it('pre-fills take turns and the turn length for an auto-rotating chore', async () => {
    const rotating = makeChore({
      id: 7,
      title: 'Water plants',
      assignment_type: 'alphabetical',
      turn_length: 3,
      household: { id: 4, name: 'Beach House' },
      assignees: [makeUser({ id: 2, first_name: 'Jo', last_name: 'Ng' })],
    })
    mockFetch([
      { path: '/api/v1/chores/7', method: 'GET', body: rotating },
      {
        path: MEMBERS,
        method: 'GET',
        body: page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]),
      },
      { path: TAGS, method: 'GET', body: page([]) },
    ])
    renderEdit()

    expect(await screen.findByDisplayValue('Water plants')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Take turns' })).toBeChecked()
    expect(screen.getByLabelText('Turn length')).toHaveValue(3)
  })

  it('pre-fills the interval and the pinned weekdays, and saves them untouched', async () => {
    const pinned = makeChore({
      id: 7,
      title: 'Washing machine',
      repeats: 'weekly',
      repeat_interval: 2,
      weekdays: [1, 4],
      household: { id: 4, name: 'Beach House' },
    })
    const fetchMock = mockFetch([
      { path: '/api/v1/chores/7', method: 'GET', body: pinned },
      { path: MEMBERS, method: 'GET', body: page([]) },
      { path: TAGS, method: 'GET', body: page([]) },
      { path: '/api/v1/chores/7', method: 'PATCH', body: pinned },
    ])
    renderEdit()

    expect(await screen.findByDisplayValue('Washing machine')).toBeInTheDocument()
    expect(screen.getByLabelText('Repeat every')).toHaveValue(2)
    expect(screen.getByRole('button', { name: 'Tuesday' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Friday' })).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('chores-list')
    // ChoreUpdate is a full replace, so an untouched save must resend both fields.
    expect(patchBody(fetchMock)).toMatchObject({ repeat_interval: 2, weekdays: [1, 4] })
  })

  it('hides the start date for an unscheduled chore and resends it as null', async () => {
    // The API stores no start date for these, so the form receives null and must not render
    // an empty date field. ChoreUpdate is a full replace, so the save has to resend the null
    // rather than inventing today's date.
    const unscheduled = makeChore({
      id: 7,
      title: 'Sort the loft',
      repeats: 'manual',
      start_date: null,
      household: { id: 4, name: 'Beach House' },
    })
    const fetchMock = mockFetch([
      { path: '/api/v1/chores/7', method: 'GET', body: unscheduled },
      { path: MEMBERS, method: 'GET', body: page([]) },
      { path: TAGS, method: 'GET', body: page([]) },
      { path: '/api/v1/chores/7', method: 'PATCH', body: unscheduled },
    ])
    renderEdit()

    expect(await screen.findByDisplayValue('Sort the loft')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Start date/ })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('chores-list')
    expect(patchBody(fetchMock)).toMatchObject({ repeats: 'manual', start_date: null })
  })

  it('unpins a chore when every weekday is cleared', async () => {
    const pinned = makeChore({
      id: 7,
      title: 'Washing machine',
      repeats: 'weekly',
      weekdays: [1],
      household: { id: 4, name: 'Beach House' },
    })
    const fetchMock = mockFetch([
      { path: '/api/v1/chores/7', method: 'GET', body: pinned },
      { path: MEMBERS, method: 'GET', body: page([]) },
      { path: TAGS, method: 'GET', body: page([]) },
      { path: '/api/v1/chores/7', method: 'PATCH', body: pinned },
    ])
    renderEdit()

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    await screen.findByDisplayValue('Washing machine')
    await user.click(screen.getByRole('button', { name: 'Tuesday' }))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await screen.findByText('chores-list')
    // An empty selection is the form's way of sending "unpinned".
    expect(patchBody(fetchMock)).toMatchObject({ weekdays: null })
  })

  it('pre-fills the current assignee for a manual chore', async () => {
    const jo = makeUser({ id: 2, first_name: 'Jo', last_name: 'Ng' })
    const manual = makeChore({
      id: 7,
      title: 'Dishes',
      assignment_type: 'manual',
      household: { id: 4, name: 'Beach House' },
      assignees: [jo],
      current_assignee: jo,
    })
    mockFetch([
      { path: '/api/v1/chores/7', method: 'GET', body: manual },
      {
        path: MEMBERS,
        method: 'GET',
        body: page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]),
      },
      { path: TAGS, method: 'GET', body: page([]) },
    ])
    renderEdit()

    await screen.findByDisplayValue('Dishes')
    expect(
      within(screen.getByRole('combobox', { name: 'Currently assigned to' })).getByText('Jo Ng'),
    ).toBeInTheDocument()
  })

  it('lets an auto-rotating chore be handed to someone else, and says it is one turn', async () => {
    const jo = makeUser({ id: 2, first_name: 'Jo', last_name: 'Ng' })
    const sam = makeUser({ id: 3, first_name: 'Sam', last_name: 'Lee' })
    const rotating = makeChore({
      id: 7,
      title: 'Dishes',
      assignment_type: 'random',
      household: { id: 4, name: 'Beach House' },
      assignees: [jo, sam],
      current_assignee: jo,
    })
    const fetchMock = mockFetch([
      { path: '/api/v1/chores/7', method: 'GET', body: rotating },
      {
        path: MEMBERS,
        method: 'GET',
        body: page([
          makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
          makeHouseholdMember({ id: 3, first_name: 'Sam', last_name: 'Lee' }),
        ]),
      },
      { path: TAGS, method: 'GET', body: page([]) },
      { path: '/api/v1/chores/7', method: 'PATCH', body: rotating },
    ])
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByDisplayValue('Dishes')
    // The picker used to be manual-only, so a random chore offered no way off
    // whoever it had landed on.
    const picker = screen.getByRole('combobox', { name: 'Currently assigned to' })
    expect(within(picker).getByText('Jo Ng')).toBeInTheDocument()
    // The override lasts one turn; the next completion re-derives from the strategy.
    expect(
      screen.getByText('Applies to the current turn; the next one follows the rotation again.'),
    ).toBeInTheDocument()

    await user.click(picker)
    await user.click(await screen.findByRole('option', { name: 'Sam Lee' }))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await screen.findByText('chores-list')
    expect(patchBody(fetchMock)).toMatchObject({ current_assignee_id: 3 })
  })

  it('offers no assignee picker at all when the chore has nobody assigned', async () => {
    mockFetch([
      {
        path: '/api/v1/chores/7',
        method: 'GET',
        body: makeChore({
          id: 7,
          title: 'Dishes',
          assignment_type: 'random',
          household: { id: 4, name: 'Beach House' },
          assignees: [],
          current_assignee: null,
        }),
      },
      { path: MEMBERS, method: 'GET', body: page([]) },
      { path: TAGS, method: 'GET', body: page([]) },
    ])
    renderEdit()

    await screen.findByDisplayValue('Dishes')
    // An empty pool is ordinary on a shared chore. Without the pool check the edit
    // page would render an empty Select on its placeholder, plus the turn hint.
    expect(
      screen.queryByRole('combobox', { name: 'Currently assigned to' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/Applies to the current turn/)).not.toBeInTheDocument()
  })

  it('does not offer the turn hint for a manual chore, whose pick is not temporary', async () => {
    const jo = makeUser({ id: 2, first_name: 'Jo', last_name: 'Ng' })
    mockFetch([
      {
        path: '/api/v1/chores/7',
        method: 'GET',
        body: makeChore({
          id: 7,
          title: 'Dishes',
          assignment_type: 'manual',
          household: { id: 4, name: 'Beach House' },
          assignees: [jo],
          current_assignee: jo,
        }),
      },
      {
        path: MEMBERS,
        method: 'GET',
        body: page([makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' })]),
      },
      { path: TAGS, method: 'GET', body: page([]) },
    ])
    renderEdit()

    await screen.findByDisplayValue('Dishes')
    expect(screen.getByRole('combobox', { name: 'Currently assigned to' })).toBeInTheDocument()
    expect(screen.queryByText(/Applies to the current turn/)).not.toBeInTheDocument()
  })

  it('saves changes with a PATCH that omits the household, then navigates', async () => {
    const fetchMock = editMocks()
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    const title = await screen.findByDisplayValue('Scrub the tub')
    await user.clear(title)
    await user.type(title, 'Deep clean the tub')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText('chores-list')).toBeInTheDocument()
    const body = patchBody(fetchMock)
    expect(body).toMatchObject({ title: 'Deep clean the tub', assignee_ids: [2], tag_ids: [3] })
    expect(body).not.toHaveProperty('household_id')
  })

  it('surfaces an update error and stays on the form', async () => {
    editMocks({
      patchStatus: 400,
      patchBody: { detail: 'Assignees must be members of your household' },
    })
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await user.click(await screen.findByRole('button', { name: 'Save changes' }))

    expect(
      await screen.findByText('Assignees must be members of your household'),
    ).toBeInTheDocument()
  })
})

describe('clearing the current assignee', () => {
  // makeUser for the chore's own assignees (ChoreRead embeds the full user), makeHouseholdMember
  // for the members endpoint (data-minimised: no email). Same split as the tests above.
  const jo = makeUser({ id: 2, first_name: 'Jo', last_name: 'Ng' })
  const sam = makeUser({ id: 3, first_name: 'Sam', last_name: 'Lee' })
  const members = [
    makeHouseholdMember({ id: 2, first_name: 'Jo', last_name: 'Ng' }),
    makeHouseholdMember({ id: 3, first_name: 'Sam', last_name: 'Lee' }),
  ]

  function mocks(chore: ReturnType<typeof makeChore>) {
    return [
      { path: '/api/v1/chores/7', method: 'GET' as const, body: chore },
      { path: MEMBERS, method: 'GET' as const, body: page(members) },
      { path: TAGS, method: 'GET' as const, body: page([]) },
      { path: '/api/v1/chores/7', method: 'PATCH' as const, body: chore },
    ]
  }

  const assigned = makeChore({
    id: 7,
    title: 'Dishes',
    assignment_type: 'manual',
    household: { id: 4, name: 'Beach House' },
    assignees: [jo, sam],
    current_assignee: jo,
  })

  it('hands the chore back to the household', async () => {
    // The point of the feature: a manual chore stuck on one person, handed back to everyone.
    // clear_current_assignee rather than current_assignee_id: null, because null means "no
    // opinion" server-side and would keep Jo.
    const fetchMock = mockFetch(mocks(assigned))
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByDisplayValue('Dishes')
    const picker = screen.getByRole('combobox', { name: 'Currently assigned to' })
    expect(within(picker).getByText('Jo Ng')).toBeInTheDocument()

    await user.click(picker)
    await user.click(await screen.findByRole('option', { name: 'Nobody in particular' }))
    expect(screen.getByText('Shown to everyone in the household.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('chores-list')
    expect(patchBody(fetchMock)).toMatchObject({
      clear_current_assignee: true,
      current_assignee_id: null,
    })
  })

  it('does not send the flag when a person is chosen', async () => {
    // Guards the other direction: picking someone after choosing nobody has to turn the flag
    // back off, or the API would clear the assignee the user just selected.
    const fetchMock = mockFetch(mocks(assigned))
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByDisplayValue('Dishes')
    const picker = screen.getByRole('combobox', { name: 'Currently assigned to' })
    await user.click(picker)
    await user.click(await screen.findByRole('option', { name: 'Nobody in particular' }))
    await user.click(screen.getByRole('combobox', { name: 'Currently assigned to' }))
    await user.click(await screen.findByRole('option', { name: 'Sam Lee' }))

    expect(screen.queryByText('Shown to everyone in the household.')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('chores-list')
    expect(patchBody(fetchMock)).toMatchObject({
      clear_current_assignee: false,
      current_assignee_id: 3,
    })
  })

  it('does not treat an empty pool as a choice of "nobody"', async () => {
    // A chore with no assignees is *necessarily* unassigned, so seeding the flag from
    // current_assignee alone would set it from a null nobody chose. The user then adds people to
    // the pool - which makes the picker appear - and saving would keep the chore unassigned,
    // where before the flag existed the strategy would have derived somebody. Same "forced null
    // vs chosen null" distinction the flag exists to draw against current_assignee_id.
    const empty = makeChore({
      id: 7,
      title: 'Dishes',
      assignment_type: 'random',
      household: { id: 4, name: 'Beach House' },
      assignees: [],
      current_assignee: null,
    })
    const fetchMock = mockFetch(mocks(empty))
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByDisplayValue('Dishes')
    // No picker yet: it needs a non-empty pool.
    expect(
      screen.queryByRole('combobox', { name: 'Currently assigned to' }),
    ).not.toBeInTheDocument()

    // Add somebody, which reveals the picker.
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('option', { name: 'Jo Ng' }))
    await user.keyboard('{Escape}')
    expect(screen.getByRole('combobox', { name: 'Currently assigned to' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('chores-list')
    // The strategy gets to pick, exactly as it did before this flag existed.
    expect(patchBody(fetchMock)).toMatchObject({ clear_current_assignee: false })
  })

  it('opens on "nobody" for a chore that is already unassigned', async () => {
    // Seeded from the chore, so saving an unrelated edit cannot quietly re-derive an assignee
    // for a chore someone deliberately shared. The pool is non-empty, which is what makes the
    // picker show at all.
    const shared = makeChore({
      id: 7,
      title: 'Dishes',
      assignment_type: 'manual',
      household: { id: 4, name: 'Beach House' },
      assignees: [jo, sam],
      current_assignee: null,
    })
    const fetchMock = mockFetch(mocks(shared))
    renderEdit()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    await screen.findByDisplayValue('Dishes')
    const picker = screen.getByRole('combobox', { name: 'Currently assigned to' })
    expect(within(picker).getByText('Nobody in particular')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('chores-list')
    expect(patchBody(fetchMock)).toMatchObject({ clear_current_assignee: true })
  })
})

describe('per-household role', () => {
  it('leaves for the chores list when the chore is not in a household you organise', async () => {
    // RequireRole only proves the caller organises *somewhere*, and reading a chore is open
    // to every role, so this is the one check that can catch "organiser here, helper there".
    // The chore lives in household 4; the caller organises 1 and is a helper in 4.
    const fetchMock = mockFetch([{ path: '/api/v1/chores/7', method: 'GET', body: savedChore }])
    renderWithProviders(
      <Routes>
        <Route path="/chores/:id/edit" element={<ChoreEdit />} />
        <Route path="/chores" element={<div>chores-list</div>} />
      </Routes>,
      {
        authValue: {
          user: me,
          memberships: [
            { household_id: 1, role: 'organiser' },
            { household_id: 4, role: 'helper' },
          ],
        },
        route: '/chores/7/edit',
      },
    )

    expect(await screen.findByText('chores-list')).toBeInTheDocument()
    // It leaves before asking for that household's tags, which is organiser-only and would
    // have failed the load with a message about nothing in particular.
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/v1/tags'))).toBe(false)
  })
})
