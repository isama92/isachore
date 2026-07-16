import { describe, expect, it } from 'vitest'
import { initials } from './avatar'

describe('initials', () => {
  it('takes the first and last initial of a multi-word name', () => {
    expect(initials('Ada Lovelace')).toBe('AL')
    expect(initials('Jan Willem de Vries')).toBe('JV')
  })

  it('takes the first two letters of a single-word name', () => {
    expect(initials('Ada')).toBe('AD')
    expect(initials('x')).toBe('X')
  })

  it('collapses surrounding and repeated whitespace', () => {
    expect(initials('  Ada   Lovelace  ')).toBe('AL')
  })

  it('falls back to ? for an empty or blank name', () => {
    expect(initials('')).toBe('?')
    expect(initials('   ')).toBe('?')
  })
})
