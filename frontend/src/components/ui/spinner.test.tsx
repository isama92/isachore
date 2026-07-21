import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Spinner } from './spinner'

describe('Spinner', () => {
  it('exposes a status role with screen-reader-only label text', () => {
    render(<Spinner label="Loading" />)
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.getByText('Loading')).toBeInTheDocument()
  })

  it('renders without a label (no status text)', () => {
    render(<Spinner />)
    const status = screen.getByRole('status')
    expect(status).toBeInTheDocument()
    expect(status.textContent).toBe('')
  })

  it('applies the requested size class', () => {
    const { container } = render(<Spinner size="lg" />)
    expect(container.querySelector('.size-9')).toBeTruthy()
  })
})
