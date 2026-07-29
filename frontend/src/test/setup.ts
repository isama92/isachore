import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
// Initialise the i18next singleton so components calling useTranslation() render
// (no provider wrapper needed). Default language is English, so string-asserting
// tests keep matching en.json verbatim.
import i18n from '../i18n/i18n'

// jsdom lacks a handful of APIs that Radix UI primitives (dialog, select,
// popover, ...) call. Define them as plain assignments, not vi.stubGlobal, so
// the afterEach teardown below does not strip them between tests.
Element.prototype.hasPointerCapture = () => false
Element.prototype.setPointerCapture = () => {}
Element.prototype.releasePointerCapture = () => {}
Element.prototype.scrollIntoView = () => {}

window.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// ProseMirror (under Tiptap, in the rich text editor) measures the selection to decide where
// the caret and decorations sit. jsdom implements Range but returns nothing from its geometry
// methods, so these are stubs rather than fakes: the editor's *document* behaviour is what the
// tests assert, and none of them depend on a real coordinate. Same plain-assignment reason as
// the Radix stubs above - vi.unstubAllGlobals() must not strip them.
Range.prototype.getClientRects = () =>
  ({
    length: 0,
    item: () => null,
    [Symbol.iterator]: function* () {},
  }) as unknown as DOMRectList
Range.prototype.getBoundingClientRect = () => new DOMRect()
// ProseMirror's mousedown handler resolves a click to a document position via
// posAtCoords -> document.elementFromPoint, which jsdom does not implement at all (it throws
// rather than returning nothing). Returning null is the "no element there" answer ProseMirror
// already handles, so a click is a no-op instead of an uncaught TypeError. Tests place the
// caret by focusing the editable, not by clicking, precisely because a real hit test is what
// jsdom cannot give us.
document.elementFromPoint = () => null

// The Profile page's scroll-spy submenu constructs an IntersectionObserver,
// which jsdom does not implement. A no-op stub is enough: tests drive the DOM
// directly and never rely on scroll-position callbacks firing.
window.IntersectionObserver = class IntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly thresholds = []
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
} as unknown as typeof IntersectionObserver

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  // The theme provider writes localStorage and sets the <html> class and
  // data-theme / data-accent attributes; reset them all so one test's flavour
  // cannot leak into the next test's initial theme.
  localStorage.clear()
  document.documentElement.classList.remove('dark')
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('data-accent')
  // The i18n instance is a module singleton that survives across tests; reset it
  // to English so a test that switched to Italian cannot leak into the next.
  void i18n.changeLanguage('en')
})
