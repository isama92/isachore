import { describe, expect, it } from 'vitest'
import { fullName, initials } from './user'

describe('fullName', () => {
  it('joins first and last name with a space', () => {
    expect(fullName({ first_name: 'Ada', last_name: 'Lovelace' })).toBe('Ada Lovelace')
  })

  it('trims when a field is blank', () => {
    expect(fullName({ first_name: 'Ada', last_name: '' })).toBe('Ada')
    expect(fullName({ first_name: '', last_name: 'Lovelace' })).toBe('Lovelace')
  })
})

describe('initials', () => {
  it('takes the first letter of each name, uppercased', () => {
    expect(initials({ first_name: 'Ada', last_name: 'Lovelace' })).toBe('AL')
    expect(initials({ first_name: 'jan', last_name: 'vries' })).toBe('JV')
  })

  it('uses only the populated field when one is blank', () => {
    expect(initials({ first_name: 'Ada', last_name: '' })).toBe('A')
    expect(initials({ first_name: '', last_name: 'Lovelace' })).toBe('L')
  })

  it('falls back to ? when both names are blank', () => {
    expect(initials({ first_name: '', last_name: '' })).toBe('?')
    expect(initials({ first_name: '  ', last_name: '  ' })).toBe('?')
  })
})
