import { describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test/utils'
import { TimezoneSelect } from './TimezoneSelect'

// `pointerEventsCheck: 0` because Radix sets pointer-events:none on the body while the
// popover is open; portaled content is queried through the dialog role.
const setup = () => userEvent.setup({ pointerEventsCheck: 0 })

describe('TimezoneSelect', () => {
  it('shows the current zone with its offset, underscores expanded', () => {
    renderWithProviders(<TimezoneSelect value="America/New_York" onChange={vi.fn()} />)
    // "New_York" is an IANA encoding artefact, not something to show a user.
    expect(screen.getByRole('button')).toHaveTextContent('America / New York')
    expect(screen.getByRole('button')).toHaveTextContent(/GMT[+-]/)
  })

  it('opens on the current zone rather than at the top of the list', async () => {
    const user = setup()
    renderWithProviders(<TimezoneSelect value="Europe/Amsterdam" onChange={vi.fn()} />)

    await user.click(screen.getByRole('button'))

    // cmdk scrolls its highlighted row into view, so highlighting the stored zone is what
    // saves an owner from arriving at Africa/Abidjan with 400 rows between them and their
    // own. Uncontrolled, cmdk would highlight the first item instead.
    const dialog = within(await screen.findByRole('dialog'))
    const current = dialog.getByRole('option', { name: /Europe \/ Amsterdam/ })
    expect(current).toHaveAttribute('aria-selected', 'true')
    expect(dialog.getByRole('option', { name: /^UTC/ })).toHaveAttribute('aria-selected', 'false')
  })

  it('filters the list by search and reports the IANA name on select', async () => {
    const onChange = vi.fn()
    const user = setup()
    renderWithProviders(<TimezoneSelect value="UTC" onChange={onChange} />)

    await user.click(screen.getByRole('button'))
    await user.type(await screen.findByPlaceholderText('Search timezones'), 'Amsterdam')

    const dialog = within(await screen.findByRole('dialog'))
    await user.click(await dialog.findByText('Europe / Amsterdam'))

    // The label is prettified but the value handed back is the raw IANA name, which is what
    // the API stores and what the backend validates.
    expect(onChange).toHaveBeenCalledWith('Europe/Amsterdam')
  })

  it('searches the offset as well as the name', async () => {
    const user = setup()
    renderWithProviders(<TimezoneSelect value="UTC" onChange={vi.fn()} />)

    await user.click(screen.getByRole('button'))
    // The `keywords` on each item carry the offset, so a user who knows they are "GMT+9" but
    // not which city IANA named their zone after can still find it.
    await user.type(await screen.findByPlaceholderText('Search timezones'), 'GMT+9')

    const dialog = within(await screen.findByRole('dialog'))
    expect(await dialog.findByText(/Tokyo/)).toBeInTheDocument()
  })

  it('reports no match rather than an empty list', async () => {
    const user = setup()
    renderWithProviders(<TimezoneSelect value="UTC" onChange={vi.fn()} />)

    await user.click(screen.getByRole('button'))
    await user.type(await screen.findByPlaceholderText('Search timezones'), 'Olympus Mons')

    const dialog = within(await screen.findByRole('dialog'))
    expect(await dialog.findByText('No matching timezone')).toBeInTheDocument()
  })
})
