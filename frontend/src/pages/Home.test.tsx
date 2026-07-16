import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import Home from './Home'
import { renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

describe('Home', () => {
  it('greets the user and links to chores management', () => {
    renderWithProviders(<Home />, {
      authValue: { user: makeUser({ first_name: 'Alex', last_name: 'Kim' }) },
    })

    expect(screen.getByText('Hi Alex Kim')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Manage chores' })).toHaveAttribute('href', '/chores')
  })
})
