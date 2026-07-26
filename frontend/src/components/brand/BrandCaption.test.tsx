import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import BrandCaption from './BrandCaption'
import { CAPTION_D, CAPTION_VIEWBOX } from './paths'

describe('BrandCaption', () => {
  it('draws the handwritten caption in the accent colour', () => {
    const { container } = render(<BrandCaption />)

    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('viewBox', CAPTION_VIEWBOX)
    expect(svg).toHaveClass('fill-primary')
    expect(container.querySelector('path')).toHaveAttribute('d', CAPTION_D)
  })

  it('is sized by width, since the phrase is nearly 2:1', () => {
    const { container } = render(<BrandCaption />)
    // A height-driven size would render it around 20px wide and unreadable, so the
    // default must constrain width and let height follow.
    expect(container.querySelector('svg')).toHaveClass('w-20', 'h-auto')
  })

  it('is decorative artwork, so it stays out of the accessibility tree', () => {
    const { container } = render(<BrandCaption />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg).not.toHaveAttribute('aria-label')
  })

  it('accepts a width override', () => {
    const { container } = render(<BrandCaption className="w-32" />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveClass('w-32')
    expect(svg).not.toHaveClass('w-20')
  })
})
