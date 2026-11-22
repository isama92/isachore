import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InfoHint } from './InfoHint'

function renderHint() {
  return render(<InfoHint label="About taking turns">One person keeps the chore.</InfoHint>)
}

describe('InfoHint', () => {
  it('is a labelled button that shows nothing until opened', () => {
    renderHint()
    const button = screen.getByRole('button', { name: 'About taking turns' })
    expect(button).not.toHaveAttribute('aria-describedby')
    expect(screen.queryByText('One person keeps the chore.')).not.toBeInTheDocument()
  })

  it('toggles on click or tap, which is how a phone reaches it', async () => {
    const user = userEvent.setup()
    renderHint()
    const button = screen.getByRole('button', { name: 'About taking turns' })

    // A touch pointer, so the hover path cannot be what opens it.
    await user.pointer({ keys: '[TouchA]', target: button })
    expect(await screen.findByText('One person keeps the chore.')).toBeInTheDocument()
    await user.pointer({ keys: '[TouchA]', target: button })
    expect(screen.queryByText('One person keeps the chore.')).not.toBeInTheDocument()
  })

  it('opens from the keyboard and closes on Escape', async () => {
    const user = userEvent.setup()
    renderHint()

    await user.tab()
    expect(screen.getByRole('button', { name: 'About taking turns' })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(await screen.findByText('One person keeps the chore.')).toBeInTheDocument()
    // Focus stays on the icon rather than jumping into the text, so the text is announced
    // through the button's description instead.
    const button = screen.getByRole('button', { name: 'About taking turns' })
    expect(button).toHaveFocus()
    expect(button).toHaveAccessibleDescription('One person keeps the chore.')
    await user.keyboard('{Escape}')
    expect(screen.queryByText('One person keeps the chore.')).not.toBeInTheDocument()
  })

  it('opens while a mouse hovers and closes when it leaves', async () => {
    const user = userEvent.setup()
    renderHint()
    const button = screen.getByRole('button', { name: 'About taking turns' })

    await user.hover(button)
    expect(await screen.findByText('One person keeps the chore.')).toBeInTheDocument()
    await user.unhover(button)
    expect(screen.queryByText('One person keeps the chore.')).not.toBeInTheDocument()
  })

  it('pins open when clicked while hover-opened, instead of closing under the cursor', async () => {
    const user = userEvent.setup()
    renderHint()
    const button = screen.getByRole('button', { name: 'About taking turns' })

    await user.hover(button)
    await user.click(button)
    expect(screen.getByText('One person keeps the chore.')).toBeInTheDocument()
    // Pinned, so moving the mouse away leaves it open.
    await user.unhover(button)
    expect(screen.getByText('One person keeps the chore.')).toBeInTheDocument()
  })
})
