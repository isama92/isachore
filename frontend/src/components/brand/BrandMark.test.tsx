import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import BrandMark from './BrandMark'
import { HEAD_D, MARK_VIEWBOX } from './paths'

describe('BrandMark', () => {
  it('draws the traced head on a tile in the accent colour', () => {
    const { container } = render(<BrandMark />)

    const tile = container.firstElementChild
    expect(tile).toHaveClass('bg-primary')
    // The glow and the brand radius are why the tile is a DOM element and not a
    // <rect>; losing either means the mark has silently stopped matching the brand.
    expect(tile).toHaveClass('rounded-lg', 'shadow-logo')

    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('viewBox', MARK_VIEWBOX)
    expect(svg).toHaveClass('fill-primary-foreground')
    expect(container.querySelector('path')).toHaveAttribute('d', HEAD_D)
  })

  it('fills the tile, with the whiskers clipped rather than padded away', () => {
    // The face floating in a big tile is the thing this framing exists to avoid, so
    // the SVG must span the tile and the tile must clip what overflows.
    const { container } = render(<BrandMark />)
    expect(container.querySelector('svg')).toHaveClass('size-full')
    expect(container.firstElementChild).toHaveClass('overflow-hidden')
  })

  it('is decorative, so it stays out of the accessibility tree', () => {
    const { container } = render(<BrandMark />)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('takes a size override without dropping the tile styling', () => {
    const { container } = render(<BrandMark className="size-12" />)
    const tile = container.firstElementChild
    expect(tile).toHaveClass('size-12', 'bg-primary', 'rounded-lg')
    expect(tile).not.toHaveClass('size-8')
  })
})
