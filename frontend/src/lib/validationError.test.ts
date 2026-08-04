import { describe, expect, it } from 'vitest'
import i18n from '../i18n/i18n'
import { formatValidationDetail } from './validationError'

// Bodies as FastAPI actually sends them. The global afterEach in src/test/setup.ts resets
// the language to English, so each case starts from en.json.
const tooLong = {
  type: 'string_too_long',
  loc: ['body', 'title'],
  msg: 'String should have at most 255 characters',
  ctx: { max_length: 255 },
}

describe('formatValidationDetail', () => {
  it('returns null for anything that is not an issue list', () => {
    // These are the shapes handle() must keep falling back to statusText for.
    expect(formatValidationDetail('Chore not found')).toBeNull()
    expect(formatValidationDetail([])).toBeNull()
    expect(formatValidationDetail(undefined)).toBeNull()
    expect(formatValidationDetail({ msg: 'nope' })).toBeNull()
    expect(formatValidationDetail(['not an object'])).toBeNull()
  })

  it('names the field and interpolates the bound that was breached', () => {
    expect(formatValidationDetail([tooLong])).toBe('Title: Must be at most 255 characters')
  })

  it('translates the whole sentence, field label included', async () => {
    await i18n.changeLanguage('it')
    expect(formatValidationDetail([tooLong])).toBe(
      'Titolo: Deve contenere al massimo 255 caratteri',
    )
  })

  it('agrees with a bound of one', () => {
    // min_length=1 is on a chore title, both name fields, tag and household names and the
    // 2FA code, so "Must be at least 1 characters" was properly reachable.
    expect(
      formatValidationDetail([
        {
          type: 'string_too_short',
          loc: ['body', 'name'],
          msg: 'String should have at least 1 character',
          ctx: { min_length: 1 },
        },
      ]),
    ).toBe('Name: Must be at least 1 character')
  })

  it('agrees with a bound of one in Italian too', async () => {
    await i18n.changeLanguage('it')
    expect(
      formatValidationDetail([
        { type: 'too_long', loc: ['body', 'weekdays'], msg: 'x', ctx: { max_length: 1 } },
      ]),
    ).toBe('Nei giorni: Deve contenere al massimo 1 elemento')
  })

  it('falls back to pydantic English rather than rendering a raw placeholder', () => {
    // Pydantic always sends ctx for a constrained type, so this is a body that did not come
    // from pydantic. "Must be {{le}} or less" would be worse than the developer English.
    expect(
      formatValidationDetail([
        {
          type: 'less_than_equal',
          loc: ['body', 'repeat_interval'],
          msg: 'Input should be less than or equal to 365',
        },
      ]),
    ).toBe('Repeat every: Input should be less than or equal to 365')
  })

  it('falls back for a pluralised type with no bound, where the key itself would show', () => {
    // Worse than a placeholder: without `count` i18next finds neither _one nor _other and
    // returns the bare key, so the user would read "errors.validation.string_too_long".
    expect(
      formatValidationDetail([
        { type: 'string_too_long', loc: ['body', 'title'], msg: 'String is too long' },
      ]),
    ).toBe('Title: String is too long')
  })

  it('falls back when a pluralised bound is not a number', () => {
    // A non-numeric count picks no plural form either, so it has the same bare-key failure
    // as a missing one and needs the same answer.
    expect(
      formatValidationDetail([
        {
          type: 'string_too_long',
          loc: ['body', 'title'],
          msg: 'String is too long',
          ctx: { max_length: 'lots' },
        },
      ]),
    ).toBe('Title: String is too long')
  })

  it('survives a type name that collides with an Object prototype key', () => {
    // Note this does NOT pin the hasOwn guard: with `in` the lookup would return a function
    // whose `ctxKey` is undefined, and the missing-bound check would send it to the same
    // fallback. It is here as an adversarial input, not as a guard test.
    expect(
      formatValidationDetail([
        { type: 'constructor', loc: ['body', 'title'], msg: 'Something odd' },
      ]),
    ).toBe('Title: Something odd')
  })

  it('reads a numeric bound out of ctx for the query-parameter types', () => {
    expect(
      formatValidationDetail([
        {
          type: 'less_than_equal',
          loc: ['body', 'repeat_interval'],
          msg: 'Input should be less than or equal to 365',
          ctx: { le: 365 },
        },
      ]),
    ).toBe('Repeat every: Must be 365 or less')
  })

  it('reports a missing field by name', () => {
    expect(
      formatValidationDetail([{ type: 'missing', loc: ['body', 'title'], msg: 'Field required' }]),
    ).toBe('Title: This is required')
  })

  it('names the list, not the offending index', () => {
    // `loc` ends in the array position; "item 3 must be 6 or less" would be a worse answer
    // than naming the picker the user can actually see.
    expect(
      formatValidationDetail([
        {
          type: 'less_than_equal',
          loc: ['body', 'weekdays', 3],
          msg: 'Input should be less than or equal to 6',
          ctx: { le: 6 },
        },
      ]),
    ).toBe('On these days: Must be 6 or less')
  })

  it('unwraps a custom validator, dropping pydantic itself out of the sentence', () => {
    expect(
      formatValidationDetail([
        {
          type: 'value_error',
          loc: ['body'],
          msg: 'Value error, A start date is required unless the chore is unscheduled',
        },
      ]),
    ).toBe('A start date is required unless the chore is unscheduled')
  })

  it('answers an EmailStr rejection itself rather than passing its wording on', () => {
    expect(
      formatValidationDetail([
        {
          type: 'value_error',
          loc: ['body', 'email'],
          msg: 'value is not a valid email address: The part after the @-sign is not valid.',
        },
      ]),
    ).toBe('Email: Enter a valid email address')
  })

  it('falls back to pydantic English for a type it has no wording for', () => {
    expect(
      formatValidationDetail([
        { type: 'uuid_parsing', loc: ['body', 'title'], msg: 'Input should be a valid UUID' },
      ]),
    ).toBe('Title: Input should be a valid UUID')
  })

  it('falls back again when even the message is missing', () => {
    expect(formatValidationDetail([{ type: 'uuid_parsing', loc: ['body', 'title'] }])).toBe(
      'Title: This value is not valid',
    )
  })

  it('opens up the underscores of a field it has no label for', () => {
    expect(
      formatValidationDetail([
        {
          type: 'greater_than_equal',
          loc: ['query', 'page_size'],
          msg: 'Input should be greater than or equal to 1',
          ctx: { ge: 1 },
        },
      ]),
    ).toBe('page size: Must be 1 or more')
  })

  it('drops the prefix when the issue is about the whole request', () => {
    expect(
      formatValidationDetail([
        { type: 'json_invalid', loc: ['body', 0], msg: 'JSON decode error' },
      ]),
    ).toBe('The request was malformed')
  })

  it('joins several issues and collapses duplicates', () => {
    expect(
      formatValidationDetail([
        { type: 'missing', loc: ['body', 'title'], msg: 'Field required' },
        { type: 'missing', loc: ['body', 'repeats'], msg: 'Field required' },
        // Same complaint about two items of one list: one sentence, not two.
        { type: 'less_than_equal', loc: ['body', 'weekdays', 0], ctx: { le: 6 }, msg: 'x' },
        { type: 'less_than_equal', loc: ['body', 'weekdays', 1], ctx: { le: 6 }, msg: 'x' },
      ]),
    ).toBe('Title: This is required; Repeats: This is required; On these days: Must be 6 or less')
  })

  it('does not let a ctx key reach i18next as one of its own options', () => {
    // `count` would switch on pluralisation and pick a _one/_other key that does not
    // exist; passing ctx under `replace` is what confines it to interpolation.
    expect(
      formatValidationDetail([
        {
          type: 'too_long',
          loc: ['body', 'weekdays'],
          msg: 'List should have at most 7 items',
          ctx: { max_length: 7, count: 99 },
        },
      ]),
    ).toBe('On these days: Must have at most 7 items')
  })
})
