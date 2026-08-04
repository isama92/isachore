import { describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { browserTimezone } from '../../lib/timezones'
import { renderWithProviders } from '../../test/utils'
import { HouseholdForm } from './HouseholdForm'

const setup = () => userEvent.setup({ pointerEventsCheck: 0 })

function render(props: Partial<Parameters<typeof HouseholdForm>[0]> = {}) {
  const onSubmit = vi.fn<(v: { name: string; timezone: string }) => Promise<void>>(() =>
    Promise.resolve(),
  )
  renderWithProviders(
    <HouseholdForm submitLabel="Save" cancelTo="/households" onSubmit={onSubmit} {...props} />,
  )
  return onSubmit
}

async function pickTimezone(user: ReturnType<typeof setup>, search: string, label: string) {
  await user.click(screen.getByLabelText('Timezone'))
  await user.type(await screen.findByPlaceholderText('Search timezones'), search)
  const dialog = within(await screen.findByRole('dialog'))
  await user.click(await dialog.findByText(label))
}

describe('HouseholdForm', () => {
  it('defaults a new household to the browser timezone', async () => {
    const user = setup()
    const onSubmit = render()

    await user.type(screen.getByLabelText('Name'), 'Beach House')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    // Not a literal: the detected zone depends on the machine, and "whatever the browser
    // says" is the actual contract.
    expect(onSubmit).toHaveBeenCalledWith({
      name: 'Beach House',
      timezone: browserTimezone(),
    })
  })

  it('submits a changed timezone on create with no confirmation', async () => {
    const user = setup()
    const onSubmit = render()

    await user.type(screen.getByLabelText('Name'), 'Beach House')
    await pickTimezone(user, 'Amsterdam', 'Europe / Amsterdam')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    // Creating re-dates nothing - there are no chores yet - so the dialog would be noise.
    // `initialTimezone` being absent is what says "this is a create".
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(onSubmit).toHaveBeenCalledWith({ name: 'Beach House', timezone: 'Europe/Amsterdam' })
  })

  it('saves an edit without confirming when the timezone did not move', async () => {
    const user = setup()
    const onSubmit = render({ initialName: 'Flat', initialTimezone: 'UTC' })

    await user.clear(screen.getByLabelText('Name'))
    await user.type(screen.getByLabelText('Name'), 'Renamed')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(onSubmit).toHaveBeenCalledWith({ name: 'Renamed', timezone: 'UTC' })
  })

  it('confirms before saving an edit that moves the timezone', async () => {
    const user = setup()
    const onSubmit = render({ initialName: 'Flat', initialTimezone: 'UTC' })

    await pickTimezone(user, 'Amsterdam', 'Europe / Amsterdam')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    // Nothing is sent until the dialog is answered: this PATCH re-dates every scheduled
    // chore in the household.
    expect(onSubmit).not.toHaveBeenCalled()
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Change timezone' }))

    expect(onSubmit).toHaveBeenCalledWith({ name: 'Flat', timezone: 'Europe/Amsterdam' })
  })

  it('cancelling the confirmation sends nothing and keeps the chosen zone on screen', async () => {
    const user = setup()
    const onSubmit = render({ initialName: 'Flat', initialTimezone: 'UTC' })

    await pickTimezone(user, 'Amsterdam', 'Europe / Amsterdam')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    const dialog = within(await screen.findByRole('alertdialog'))
    await user.click(dialog.getByRole('button', { name: 'Cancel' }))

    expect(onSubmit).not.toHaveBeenCalled()
    // No revert needed or wanted: the Select is controlled by the form's own state, which the
    // dialog never touched, so the user's choice survives for them to submit or change.
    expect(screen.getByLabelText('Timezone')).toHaveTextContent('Europe / Amsterdam')
  })
})
