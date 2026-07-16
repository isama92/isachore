import { render, screen } from '@testing-library/react'
import { Button } from './button'

describe('Button', () => {
  it('renders a native button with the default variant', () => {
    render(<Button>Save</Button>)
    const btn = screen.getByRole('button', { name: 'Save' })
    expect(btn).toHaveAttribute('data-slot', 'button')
    expect(btn).toHaveAttribute('data-variant', 'default')
  })

  it('reflects the chosen variant on the data attribute', () => {
    render(<Button variant="destructive">Remove</Button>)
    expect(screen.getByRole('button', { name: 'Remove' })).toHaveAttribute(
      'data-variant',
      'destructive',
    )
  })

  it('renders as its child element when asChild is set (for router links)', () => {
    render(
      <Button asChild>
        <a href="/chores">Chores</a>
      </Button>,
    )
    const link = screen.getByRole('link', { name: 'Chores' })
    expect(link).toHaveAttribute('data-slot', 'button')
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('forwards the disabled attribute', () => {
    render(<Button disabled>Wait</Button>)
    expect(screen.getByRole('button', { name: 'Wait' })).toBeDisabled()
  })
})
