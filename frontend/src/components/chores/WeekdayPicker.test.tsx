import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WeekdayPicker } from './WeekdayPicker'
import { Label } from '@/components/ui/label'
import { renderWithProviders } from '../../test/utils'

// Radix renders a multiple-selection ToggleGroup as role="toolbar" holding plain
// buttons with aria-pressed. It is only type="single" that gets radiogroup/radio and
// aria-checked, so getByRole('checkbox') and jest-dom's toBeChecked() do not apply
// here (toBeChecked actually throws on an aria-pressed button).
const pressed = (name: string) => screen.getByRole('button', { name }).getAttribute('aria-pressed')

describe('WeekdayPicker', () => {
  it('renders all seven days, named in full but labelled short', () => {
    renderWithProviders(<WeekdayPicker value={[]} onChange={() => {}} />)
    for (const day of [
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
      'Sunday',
    ])
      expect(screen.getByRole('button', { name: day })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Tuesday' })).toHaveTextContent('Tue')
  })

  it('presses exactly the selected days', () => {
    renderWithProviders(<WeekdayPicker value={[1, 4]} onChange={() => {}} />)
    expect(pressed('Tuesday')).toBe('true')
    expect(pressed('Friday')).toBe('true')
    expect(pressed('Monday')).toBe('false')
    expect(pressed('Sunday')).toBe('false')
  })

  it('adds a day and reports the selection Monday-first', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<WeekdayPicker value={[4]} onChange={onChange} />)
    await user.click(screen.getByRole('button', { name: 'Tuesday' }))
    // Radix hands back activation order ([4, 1]); the picker sorts before reporting.
    expect(onChange).toHaveBeenCalledWith([1, 4])
  })

  it('removes a day that was already pressed', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<WeekdayPicker value={[1, 4]} onChange={onChange} />)
    await user.click(screen.getByRole('button', { name: 'Friday' }))
    expect(onChange).toHaveBeenCalledWith([1])
  })

  it('reports an empty selection when the last day is removed', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<WeekdayPicker value={[1]} onChange={onChange} />)
    await user.click(screen.getByRole('button', { name: 'Tuesday' }))
    // Unpinned, which the form turns into a null weekdays payload.
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('takes its accessible name from the label it points at', () => {
    renderWithProviders(
      <>
        <Label id="weekdays-label">On these days</Label>
        <WeekdayPicker value={[]} onChange={() => {}} labelledBy="weekdays-label" />
      </>,
    )
    expect(screen.getByRole('toolbar', { name: 'On these days' })).toBeInTheDocument()
  })

  it('does not submit the surrounding form when a day is clicked', async () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(
      <form onSubmit={onSubmit}>
        <WeekdayPicker value={[]} onChange={() => {}} />
      </form>,
    )
    await user.click(screen.getByRole('button', { name: 'Wednesday' }))
    // Radix sets type="button" on the items, so they cannot act as submit buttons.
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
