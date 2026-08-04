import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { ChartContainer, ChartTooltipContent, type ChartConfig } from './chart'

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

// A stacked chart's tooltip payload carries one entry per series whatever the value, so
// `hideZero` is what stops "Skipped 0" appearing on every bucket where nothing was skipped.
const STACKED_CONFIG: ChartConfig = {
  count: { label: 'Completed', color: 'var(--color-primary)' },
  skipped: { label: 'Skipped', color: 'var(--color-stat-skipped)' },
}

// `ChartTooltipContent` needs only the config context, but the sole provider is
// `ChartContainer`, whose ResponsiveContainer skips its children while it measures 0x0 - and
// jsdom reports 0 for every layout box, with setup.ts's ResizeObserver stub never firing. So
// give the box a size for the duration of these tests. Local rather than in setup.ts: nothing
// else in the suite renders inside a chart, and a global size would quietly change how the
// other Recharts call sites behave under test.
function renderTooltip(props: Record<string, unknown>) {
  const original = HTMLElement.prototype.getBoundingClientRect
  HTMLElement.prototype.getBoundingClientRect = () =>
    ({ width: 320, height: 200, top: 0, left: 0, right: 320, bottom: 200, x: 0, y: 0 }) as DOMRect
  try {
    const { container } = render(
      <ChartContainer config={STACKED_CONFIG}>
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <ChartTooltipContent {...(props as any)} />
      </ChartContainer>,
    )
    // The injected <style> is a sibling of the rows, so read only the tooltip's own text.
    return container.querySelector<HTMLElement>('[data-slot=chart] > div')?.textContent ?? ''
  } finally {
    HTMLElement.prototype.getBoundingClientRect = original
  }
}

// Two series, only one of which happened. `type` is set so the pre-existing
// `type !== 'none'` filter keeps both rows: a test whose rows that filter drops
// would pass with `hideZero` gone and pin nothing.
const MIXED = [
  { name: 'count', dataKey: 'count', value: 2, type: 'rect' },
  { name: 'skipped', dataKey: 'skipped', value: 0, type: 'rect' },
]

describe('ChartTooltipContent hideZero', () => {
  it('lists a zero-valued series by default', () => {
    const text = renderTooltip({ active: true, payload: MIXED, hideLabel: true })
    expect(text).toContain('Completed')
    expect(text).toContain('Skipped')
  })

  it('drops the zero-valued series when asked, keeping the rest', () => {
    const text = renderTooltip({ active: true, payload: MIXED, hideLabel: true, hideZero: true })
    expect(text).toContain('Completed')
    expect(text).toContain('2')
    expect(text).not.toContain('Skipped')
  })

  it('renders nothing at all when every series is zero', () => {
    const text = renderTooltip({
      active: true,
      hideLabel: true,
      hideZero: true,
      payload: [
        { name: 'count', dataKey: 'count', value: 0, type: 'rect' },
        { name: 'skipped', dataKey: 'skipped', value: 0, type: 'rect' },
      ],
    })
    // Not an empty tooltip box: a bar chart's tooltip triggers on the category, so a day
    // with no activity is hoverable and would otherwise show a bordered blank.
    expect(text).toBe('')
  })
})
