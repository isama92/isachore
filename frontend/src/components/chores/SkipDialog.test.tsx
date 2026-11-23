import { describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SkipDialog from './SkipDialog'
import { makeDueChore } from '../../test/fixtures'
import { renderWithProviders } from '../../test/utils'
import type { DueChore } from '@/lib/types'

// type="single" ToggleGroup: Radix renders a radiogroup of role="radio" items, so the
// choice is read with aria-checked.

function open(chore: DueChore) {
  const onConfirm = vi.fn()
  const onClose = vi.fn()
  renderWithProviders(<SkipDialog chore={chore} onClose={onClose} onConfirm={onConfirm} />)
  return { onConfirm, onClose, dialog: screen.getByRole('alertdialog') }
}

const weekIgnored = (overrides: Partial<DueChore> = {}) =>
  makeDueChore({
    title: 'Dishes',
    repeats: 'daily',
    days_until_due: -7,
    status: 'overdue',
    due_count: 8,
    ...overrides,
  })

describe('SkipDialog', () => {
  it.each([0, 1])('is the plain confirm when %i occurrences are due', async (due) => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { onConfirm, dialog } = open(makeDueChore({ title: 'Dishes', due_count: due }))

    expect(within(dialog).queryByRole('radiogroup')).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Skip it' }))
    expect(onConfirm).toHaveBeenCalledWith(null)
  })

  it('offers one, all or custom when several are due, defaulting to all', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { onConfirm, dialog } = open(weekIgnored())

    expect(within(dialog).getByText(/^8 days due by today\./)).toBeInTheDocument()
    expect(within(dialog).getByRole('radio', { name: 'All until today (8)' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    // Sent as the number the user saw, not as "whatever is due now": that is the guard
    // against a stale page.
    await user.click(within(dialog).getByRole('button', { name: 'Skip 8 days' }))
    expect(onConfirm).toHaveBeenCalledWith(8)
  })

  it('confirms a single occurrence', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { onConfirm, dialog } = open(weekIgnored())

    await user.click(within(dialog).getByRole('radio', { name: 'Just 1' }))
    await user.click(within(dialog).getByRole('button', { name: 'Skip 1 day' }))
    expect(onConfirm).toHaveBeenCalledWith(1)
  })

  it('keeps a choice when the selected option is pressed again', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { dialog } = open(weekIgnored())

    const all = within(dialog).getByRole('radio', { name: 'All until today (8)' })
    await user.click(all)
    expect(all).toHaveAttribute('aria-checked', 'true')
    expect(within(dialog).getByRole('button', { name: 'Skip 8 days' })).toBeEnabled()
  })

  it('takes a custom number between 1 and the due count', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { onConfirm, dialog } = open(weekIgnored())

    await user.click(within(dialog).getByRole('radio', { name: 'Custom' }))
    const input = within(dialog).getByLabelText('Number to skip')
    expect(input).toHaveAccessibleDescription('From 1 to 8')
    // Empty: nothing to confirm yet.
    expect(within(dialog).getByRole('button', { name: 'Skip it' })).toBeDisabled()

    for (const bad of ['0', '9', '2.5']) {
      await user.clear(input)
      await user.type(input, bad)
      expect(input).toHaveAttribute('aria-invalid', 'true')
      expect(within(dialog).getByRole('button', { name: 'Skip it' })).toBeDisabled()
    }

    await user.clear(input)
    await user.type(input, '3')
    expect(input).toHaveAttribute('aria-invalid', 'false')
    await user.click(within(dialog).getByRole('button', { name: 'Skip 3 days' }))
    expect(onConfirm).toHaveBeenCalledWith(3)
  })

  it('sends a custom number equal to the due count as that number', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { onConfirm, dialog } = open(weekIgnored({ due_count: 4 }))

    await user.click(within(dialog).getByRole('radio', { name: 'Custom' }))
    await user.type(within(dialog).getByLabelText('Number to skip'), '4')
    await user.click(within(dialog).getByRole('button', { name: 'Skip 4 days' }))
    expect(onConfirm).toHaveBeenCalledWith(4)
  })

  it.each([
    ['a plain week', {}],
    ['a week pinned to one day', { weekdays: [0] }],
  ])('names the unit in weeks for %s', (_, overrides) => {
    open(weekIgnored({ repeats: 'weekly', due_count: 6, ...overrides }))
    expect(screen.getByRole('button', { name: 'Skip 6 weeks' })).toBeInTheDocument()
  })

  it.each([
    ['an interval', { repeat_interval: 2 }],
    ['pinned weekdays', { repeats: 'weekly' as const, weekdays: [1, 4] }],
  ])('counts occurrences for %s, which are not one unit apart', (_, overrides) => {
    open(weekIgnored({ due_count: 3, ...overrides }))
    expect(screen.getByRole('button', { name: 'Skip 3 occurrences' })).toBeInTheDocument()
  })

  it('cancels without confirming', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const { onConfirm, onClose, dialog } = open(weekIgnored())

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })
})
