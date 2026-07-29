import { describe, expect, it } from 'vitest'
import i18n from '../i18n/i18n'
import { doneDotClass, lastDoneLabel } from './unscheduled'
import { makeUnscheduledChore } from '../test/fixtures'

const t = i18n.getFixedT('en')

describe('doneDotClass', () => {
  it('greens a chore done today', () => {
    expect(doneDotClass({ days_since_last_completion: 0 })).toBe('bg-done-recent')
  })

  it('ambers a chore done within the week, at both ends of the range', () => {
    expect(doneDotClass({ days_since_last_completion: 1 })).toBe('bg-done-week')
    expect(doneDotClass({ days_since_last_completion: 7 })).toBe('bg-done-week')
  })

  it('greys a chore done longer ago than a week', () => {
    // 8 is the first day past the threshold, so this pins the boundary rather than
    // asserting somewhere safely far away.
    expect(doneDotClass({ days_since_last_completion: 8 })).toBe('bg-done-stale')
  })

  it('greys a chore that has never been done', () => {
    expect(doneDotClass({ days_since_last_completion: null })).toBe('bg-done-stale')
  })

  it('treats a completion timestamped ahead of the clock as today', () => {
    // Guards the `<= 0` rather than `=== 0`: clock skew between the server and the
    // completion must not fall through to grey.
    expect(doneDotClass({ days_since_last_completion: -1 })).toBe('bg-done-recent')
  })

  it('never returns a due-view colour', () => {
    // The two scales cross over (done today is green, due today is yellow), so reusing a
    // bg-due-* class here would silently mean the wrong thing.
    const classes = [0, 3, 20, null].map((days) =>
      doneDotClass({ days_since_last_completion: days }),
    )
    expect(classes.every((c) => !c.startsWith('bg-due-'))).toBe(true)
  })
})

describe('lastDoneLabel', () => {
  it('reads "today" for a chore done earlier today', () => {
    expect(lastDoneLabel(t, makeUnscheduledChore({ days_since_last_completion: 0 }))).toBe(
      'Last done today',
    )
  })

  it('counts the days otherwise, singular and plural', () => {
    expect(lastDoneLabel(t, makeUnscheduledChore({ days_since_last_completion: 1 }))).toBe(
      'Last done 1 day ago',
    )
    expect(lastDoneLabel(t, makeUnscheduledChore({ days_since_last_completion: 12 }))).toBe(
      'Last done 12 days ago',
    )
  })

  it('says so when the chore has never been done', () => {
    expect(lastDoneLabel(t, makeUnscheduledChore({ days_since_last_completion: null }))).toBe(
      'Never done',
    )
  })
})
