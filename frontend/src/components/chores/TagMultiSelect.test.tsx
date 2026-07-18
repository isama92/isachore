import { describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TagMultiSelect } from './TagMultiSelect'
import { renderWithProviders } from '../../test/utils'
import { makeTag } from '../../test/fixtures'

const tags = [
  makeTag({ id: 1, name: 'deep-clean', color: '#0d9488' }),
  makeTag({ id: 2, name: 'shared', color: '#7c6bf0' }),
  makeTag({ id: 3, name: 'urgent', color: '#ef4444' }),
]

describe('TagMultiSelect', () => {
  it('shows a placeholder when nothing is selected', () => {
    renderWithProviders(<TagMultiSelect tags={tags} value={[]} onChange={() => {}} />)
    expect(screen.getByText('Select tags')).toBeInTheDocument()
  })

  it('summarises the selected tags as badges', () => {
    renderWithProviders(<TagMultiSelect tags={tags} value={[1, 3]} onChange={() => {}} />)
    const trigger = screen.getByRole('button')
    expect(within(trigger).getByText('deep-clean')).toBeInTheDocument()
    expect(within(trigger).getByText('urgent')).toBeInTheDocument()
    expect(within(trigger).queryByText('shared')).not.toBeInTheDocument()
  })

  it('filters the list with the search box', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<TagMultiSelect tags={tags} value={[]} onChange={() => {}} />)
    await user.click(screen.getByRole('button'))
    await user.type(screen.getByPlaceholderText('Search tags…'), 'urg')
    expect(await screen.findByRole('option', { name: 'urgent' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'deep-clean' })).not.toBeInTheDocument()
  })

  it('appends to the existing selection when another row is clicked', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<TagMultiSelect tags={tags} value={[1]} onChange={onChange} />)
    await user.click(screen.getByRole('button'))
    await user.click(await screen.findByRole('option', { name: 'shared' }))
    // Keeps the existing id and adds the new one (no clobber, no duplicate).
    expect(onChange).toHaveBeenCalledWith([1, 2])
  })

  it('removes a tag when a selected row is clicked', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<TagMultiSelect tags={tags} value={[1]} onChange={onChange} />)
    await user.click(screen.getByRole('button'))
    await user.click(await screen.findByRole('option', { name: 'deep-clean' }))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('shows an empty message when the search matches nothing', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderWithProviders(<TagMultiSelect tags={tags} value={[]} onChange={() => {}} />)
    await user.click(screen.getByRole('button'))
    await user.type(screen.getByPlaceholderText('Search tags…'), 'zzz')
    expect(await screen.findByText('No tags found.')).toBeInTheDocument()
  })
})
