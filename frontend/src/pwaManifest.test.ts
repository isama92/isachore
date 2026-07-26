import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { HEAD_D, MARK_VIEWBOX } from './components/brand/paths'

// The manifest and the icons are static files outside tsc's and eslint's reach,
// so nothing else would notice a typo'd filename -- the app would simply stop
// being installable, silently and only on a phone. Same reasoning as
// theme/themeInitSync.test.ts.
const publicDir = join(dirname(fileURLToPath(import.meta.url)), '../public')
const manifest = JSON.parse(readFileSync(join(publicDir, 'manifest.webmanifest'), 'utf8'))
const indexHtml = readFileSync(join(publicDir, '../index.html'), 'utf8')

type Icon = { src: string; sizes: string; type: string; purpose: string }
const icons: Icon[] = manifest.icons

describe('the web app manifest', () => {
  it('declares what a browser needs to offer an install', () => {
    expect(manifest.name).toBe('isachore')
    expect(manifest.short_name).toBe('isachore')
    expect(manifest.start_url).toBe('/')
    expect(manifest.scope).toBe('/')
    expect(manifest.display).toBe('standalone')
    expect(manifest.theme_color).toMatch(/^#[0-9a-f]{6}$/i)
    expect(manifest.background_color).toMatch(/^#[0-9a-f]{6}$/i)
  })

  it('ships the 192 and 512 icons Chrome requires', () => {
    const any = icons.filter((i) => i.purpose === 'any').map((i) => i.sizes)
    expect(any).toContain('192x192')
    expect(any).toContain('512x512')
  })

  it('ships a maskable icon, or Android letterboxes the mark', () => {
    // Without one, launchers pad the icon into a white or grey tile instead of
    // cropping it to their own shape.
    expect(icons.some((i) => i.purpose === 'maskable')).toBe(true)
  })

  it('points every icon at a file that exists', () => {
    for (const icon of icons) {
      expect(existsSync(join(publicDir, icon.src)), `missing ${icon.src}`).toBe(true)
    }
  })
})

describe('index.html', () => {
  it('links the manifest', () => {
    expect(indexHtml).toContain('rel="manifest" href="/manifest.webmanifest"')
  })

  it('links an apple-touch-icon that exists, since iOS ignores the manifest icons', () => {
    expect(indexHtml).toContain('rel="apple-touch-icon" href="/apple-touch-icon.png"')
    expect(existsSync(join(publicDir, 'apple-touch-icon.png'))).toBe(true)
  })

  it('carries the Apple standalone meta tags', () => {
    expect(indexHtml).toContain('name="apple-mobile-web-app-capable" content="yes"')
    expect(indexHtml).toContain('name="apple-mobile-web-app-title" content="isachore"')
  })
})

describe('favicon.svg and paths.ts stay the same image', () => {
  // CLAUDE.md, paths.ts, BrandMark.tsx and favicon.svg all insist these two carry
  // the same artwork under the same viewBox, and until now nothing checked it.
  // The favicon is a static file tsc and eslint never see, so a drift would only
  // show up as a browser tab that quietly stopped matching the app.
  const favicon = readFileSync(join(publicDir, 'favicon.svg'), 'utf8')

  it('draws the same path', () => {
    expect(favicon).toContain(`d="${HEAD_D}"`)
  })

  it('frames it with the same viewBox', () => {
    expect(favicon).toContain(`viewBox="${MARK_VIEWBOX}"`)
  })

  it('sizes the tile to that viewBox, so the mark is not cropped or floating', () => {
    const [x, y, w, h] = MARK_VIEWBOX.split(' ')
    expect(favicon).toContain(`x="${x}" y="${y}" width="${w}" height="${h}"`)
  })
})

// The worker's own behaviour is covered by serviceWorker.test.ts, which runs it
// rather than grepping it.
