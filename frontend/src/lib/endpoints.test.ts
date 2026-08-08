import { describe, expect, it } from 'vitest'
import { endpoints, householdResource } from './endpoints'

describe('endpoints', () => {
  it('exposes static paths under the /api/v1 prefix', () => {
    expect(endpoints.auth.me).toBe('/api/v1/auth/me')
    expect(endpoints.home).toBe('/api/v1/home')
    expect(endpoints.profile.avatar).toBe('/api/v1/profile/avatar')
    expect(endpoints.completions.filters).toBe('/api/v1/completions/filters')
    expect(endpoints.logs).toBe('/api/v1/logs')
    expect(endpoints.adminSettings.testEmail).toBe('/api/v1/admin/settings/test-email')
  })

  it('puts every admin-gated group under /api/v1/admin', () => {
    // A closed-set assertion on the rule itself, not a second guard on today's paths:
    // those are pinned exactly, both here and by the page tests, whose fetch stubs
    // carry the full prefix and so stop matching if one slips back. What this adds is
    // cover for a group that has no page test yet - a new admin surface declared on
    // the wrong prefix would otherwise reach the API before anything complained.
    for (const path of [
      endpoints.adminUsers.root,
      endpoints.adminSettings.root,
      endpoints.adminHouseholds.root,
    ]) {
      expect(path.startsWith('/api/v1/admin/')).toBe(true)
    }
    // Not admin-gated despite its name: it authenticates off the parked admin cookie,
    // and during impersonation the caller's own session is not an admin one.
    expect(endpoints.auth.stopImpersonating).toBe('/api/v1/auth/stop-impersonating')
  })

  it('builds parameterised paths from their id', () => {
    expect(endpoints.chores.byId('c1')).toBe('/api/v1/chores/c1')
    expect(endpoints.chores.complete('c1')).toBe('/api/v1/chores/c1/complete')
    expect(endpoints.completions.byId('e2')).toBe('/api/v1/completions/e2')
    expect(endpoints.tags.byId('t3')).toBe('/api/v1/tags/t3')
    expect(endpoints.households.byId('h4')).toBe('/api/v1/households/h4')
    expect(endpoints.households.members('h4')).toBe('/api/v1/households/h4/members')
    expect(endpoints.households.leave('h4')).toBe('/api/v1/households/h4/leave')
    // These share the /admin/users/{id} stem, so pin them apart explicitly.
    expect(endpoints.adminUsers.byId('u5')).toBe('/api/v1/admin/users/u5')
    expect(endpoints.adminUsers.impersonate('u5')).toBe('/api/v1/admin/users/u5/impersonate')
    expect(endpoints.adminUsers.resendConfirmation('u5')).toBe(
      '/api/v1/admin/users/u5/resend-confirmation',
    )
    expect(endpoints.adminUsers.resetTwoFactor('u5')).toBe('/api/v1/admin/users/u5/reset-2fa')
    expect(endpoints.invitations.accept('tok')).toBe('/api/v1/invitations/tok/accept')
    expect(endpoints.confirm.byToken('tok')).toBe('/api/v1/confirm/tok')
    expect(endpoints.adminHouseholds.byId('h6')).toBe('/api/v1/admin/households/h6')
    expect(endpoints.adminHouseholds.restore('h6')).toBe('/api/v1/admin/households/h6/restore')
  })

  it('accepts numeric ids (from API objects) as well as strings', () => {
    expect(endpoints.chores.complete(42)).toBe('/api/v1/chores/42/complete')
    expect(endpoints.completions.byId(7)).toBe('/api/v1/completions/7')
    expect(householdResource(endpoints.households.byId(3)).member(9)).toBe(
      '/api/v1/households/3/members/9',
    )
  })

  it('composes household sub-resources relative to either base', () => {
    const member = householdResource(endpoints.households.byId('h1'))
    expect(member.members).toBe('/api/v1/households/h1/members')
    expect(member.member('m2')).toBe('/api/v1/households/h1/members/m2')
    expect(member.invitations).toBe('/api/v1/households/h1/invitations')
    expect(member.revokeInvitation('i3')).toBe('/api/v1/households/h1/invitations/i3/revoke')

    const admin = householdResource(endpoints.adminHouseholds.byId('h1'))
    expect(admin.self).toBe('/api/v1/admin/households/h1')
    expect(admin.members).toBe('/api/v1/admin/households/h1/members')
    expect(admin.invitation('i4')).toBe('/api/v1/admin/households/h1/invitations/i4')
  })
})
