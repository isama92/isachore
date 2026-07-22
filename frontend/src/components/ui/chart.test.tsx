import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { ChartContainer, type ChartConfig } from './chart'

// ChartContainer injects a per-chart <style> block (ChartStyle) via
// dangerouslySetInnerHTML. These tests pin down that only safe config keys and
// colour values reach that block, so a future caller passing user-controlled
// input cannot break out of the declaration and inject arbitrary CSS (L6).
// A throwaway <div /> satisfies the required Recharts child; the <style>
// sibling renders regardless of chart sizing.
function renderChart(config: ChartConfig) {
  const { container } = render(
    <ChartContainer config={config}>
      <div />
    </ChartContainer>,
  )
  return container.querySelector('style')?.textContent ?? ''
}

describe('ChartStyle injection guard', () => {
  it('emits a custom property for a legit config value', () => {
    const css = renderChart({
      count: { label: 'Completions', color: 'var(--color-primary)' },
    })
    expect(css).toContain('--color-count: var(--color-primary);')
  })

  it('emits every valid declaration in a multi-entry config', () => {
    const css = renderChart({
      a: { color: '#fff' },
      b: { color: 'rgb(1, 2, 3)' },
    })
    expect(css).toContain('--color-a: #fff;')
    expect(css).toContain('--color-b: rgb(1, 2, 3);')
  })

  it('drops a declaration whose colour value could escape the CSS block', () => {
    const css = renderChart({
      evil: { color: 'red; } body { display: none } .x {' },
    })
    expect(css).not.toContain('--color-evil')
    expect(css).not.toContain('body {')
    expect(css).not.toContain('display: none')
  })

  it('drops a declaration whose key is not a plain identifier', () => {
    const css = renderChart({
      'x: red; } body {': { color: 'red' },
    })
    expect(css).not.toContain('body {')
    expect(css).not.toContain('x: red')
  })
})
