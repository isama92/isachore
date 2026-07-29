import { describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { AssigneeMultiSelect } from './AssigneeMultiSelect'
import { renderWithProviders } from '../../test/utils'
import { makeHouseholdMember } from '../../test/fixtures'

const members = [
  makeHouseholdMember({ id: 1, first_name: 'Alex', last_name: 'Kim' }),
  makeHouseholdMember({ id: 2, first_name: 'Sam', last_name: 'Rivera' }),
  makeHouseholdMember({ id: 3, first_name: 'Jordan', last_name: 'Lee' }),
]

// The strings the two call sites pass differ; the tests fix them so assertions are
// stable regardless of which context (form vs Home filter) the copy comes from.
function renderPicker(props: Partial<ComponentProps<typeof AssigneeMultiSelect>> = {}) {
  return renderWithProviders(
    <AssigneeMultiSelect
      members={members}
      value={[]}
      onChange={() => {}}
      label="Assignees"
      placeholder="Select assignees"
      searchPlaceholder="Search members…"
      emptyText="No members found."
      {...props}
    />,
  )
}

describe('AssigneeMultiSelect', () => {
  it('shows a placeholder when nothing is selected', () => {
    renderPicker()
    expect(screen.getByText('Select assignees')).toBeInTheDocument()
  })

  it('summarises the selected members as badges', () => {
    renderPicker({ value: [1, 3] })
    const trigger = screen.getByRole('button', { name: 'Assignees' })
    expect(within(trigger).getByText('Alex Kim')).toBeInTheDocument()
    expect(within(trigger).getByText('Jordan Lee')).toBeInTheDocument()
    expect(within(trigger).queryByText('Sam Rivera')).not.toBeInTheDocument()
  })

  it('filters the list with the search box', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderPicker()
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.type(screen.getByPlaceholderText('Search members…'), 'riv')
    expect(await screen.findByRole('option', { name: 'Sam Rivera' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Alex Kim' })).not.toBeInTheDocument()
  })

  it('appends to the existing selection when another row is clicked', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderPicker({ value: [1], onChange })
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('option', { name: 'Sam Rivera' }))
    // Keeps the existing id and adds the new one (no clobber, no duplicate).
    expect(onChange).toHaveBeenCalledWith([1, 2])
  })

  it('removes a member when a selected row is clicked', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderPicker({ value: [1], onChange })
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('option', { name: 'Alex Kim' }))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('removes a member via the badge × without opening the popover', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderPicker({ value: [1, 2], onChange })
    await user.click(screen.getByRole('button', { name: 'Remove Alex Kim' }))
    expect(onChange).toHaveBeenCalledWith([2])
    // The × must not toggle the popover open.
    expect(screen.queryByPlaceholderText('Search members…')).not.toBeInTheDocument()
  })

  it('removes a member via the badge × with the keyboard', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderPicker({ value: [1, 2], onChange })
    const remove = screen.getByRole('button', { name: 'Remove Alex Kim' })
    remove.focus()
    await user.keyboard('{Enter}')
    expect(onChange).toHaveBeenCalledWith([2])
    expect(screen.queryByPlaceholderText('Search members…')).not.toBeInTheDocument()
  })

  it('selects everyone with the select-all action', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderPicker({ value: [], onChange })
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('button', { name: 'Select all' }))
    expect(onChange).toHaveBeenCalledWith([1, 2, 3])
  })

  it('hides the clear action when nothing is selected', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderPicker({ value: [] })
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    expect(await screen.findByRole('button', { name: 'Select all' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument()
  })

  it('clears the selection with the clear action', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderPicker({ value: [1, 2], onChange })
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.click(await screen.findByRole('button', { name: 'Clear' }))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('shows an empty message when the search matches nothing', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderPicker()
    await user.click(screen.getByRole('button', { name: 'Assignees' }))
    await user.type(screen.getByPlaceholderText('Search members…'), 'zzz')
    expect(await screen.findByText('No members found.')).toBeInTheDocument()
  })
})
