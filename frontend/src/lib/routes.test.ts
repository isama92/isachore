import { describe, expect, it } from 'vitest'
import { routes, safeReturnPath } from './routes'

// Every parameterised route, so the consistency check below can loop over all
// of them rather than sampling one.
const editRoutes = [
  routes.chores.edit,
  routes.households.edit,
  routes.tags.edit,
  routes.admin.users.edit,
  routes.admin.households.edit,
]

describe('routes', () => {
  it('exposes every static navigation target', () => {
    expect(routes.login).toBe('/login')
    expect(routes.confirm).toBe('/confirm')
    expect(routes.invite).toBe('/invite')
    expect(routes.home).toBe('/')
    expect(routes.unscheduled).toBe('/unscheduled')
    expect(routes.profile).toBe('/profile')
    expect(routes.history).toBe('/history')
    expect(routes.statistics).toBe('/statistics')
    expect(routes.logs).toBe('/logs')
    expect(routes.chores.list).toBe('/chores')
    expect(routes.chores.new).toBe('/chores/new')
    expect(routes.households.list).toBe('/households')
    expect(routes.households.new).toBe('/households/new')
    expect(routes.tags.list).toBe('/tags')
    expect(routes.tags.new).toBe('/tags/new')
    expect(routes.admin.users.list).toBe('/admin/users')
    expect(routes.admin.users.new).toBe('/admin/users/new')
    expect(routes.admin.households.list).toBe('/admin/households')
    expect(routes.admin.households.new).toBe('/admin/households/new')
    expect(routes.admin.serverSettings).toBe('/admin/server-settings')
  })

  it('pairs each parameterised route pattern with its filled builder', () => {
    expect(routes.chores.edit.pattern).toBe('/chores/:id/edit')
    expect(routes.chores.edit.to('c1')).toBe('/chores/c1/edit')

    expect(routes.tags.edit.pattern).toBe('/tags/:id/edit')
    expect(routes.tags.edit.to(3)).toBe('/tags/3/edit')

    expect(routes.households.edit.pattern).toBe('/households/:id/edit')
    expect(routes.households.edit.to('h4')).toBe('/households/h4/edit')

    expect(routes.admin.users.edit.pattern).toBe('/admin/users/:id/edit')
    expect(routes.admin.users.edit.to(9)).toBe('/admin/users/9/edit')

    expect(routes.admin.households.edit.pattern).toBe('/admin/households/:id/edit')
    expect(routes.admin.households.edit.to('h6')).toBe('/admin/households/h6/edit')
  })

  it('keeps every filled path a concrete instance of its pattern', () => {
    // The `to(id)` output must match the `pattern` with `:id` substituted, or a
    // link would point somewhere the router does not serve (App.tsx registers
    // the pattern, the call sites navigate to the filled form).
    for (const route of editRoutes) {
      expect(route.to('X')).toBe(route.pattern.replace(':id', 'X'))
    }
  })
})

describe('safeReturnPath', () => {
  // The open-redirect guard on `?next=`. Each rejection is its own case on purpose: the
  // clauses are independent, so one `it` covering "hostile input" would keep passing after
  // any single clause was deleted, which is the trap this project keeps hitting.

  it('keeps a site-relative path', () => {
    expect(safeReturnPath('/docs')).toBe('/docs')
    expect(safeReturnPath('/chores?page=2')).toBe('/chores?page=2')
  })

  it('rejects an absolute url', () => {
    expect(safeReturnPath('https://evil.example/x')).toBeNull()
  })

  it('rejects a protocol-relative url', () => {
    // Starts with a slash, so a naive "is it relative" check waves it through, and the
    // browser reads it as a host.
    expect(safeReturnPath('//evil.example/x')).toBeNull()
  })

  it('rejects a backslash, which the parser normalises into a protocol-relative url', () => {
    expect(safeReturnPath('/\\evil.example')).toBeNull()
  })

  it('rejects a tab, LF or CR smuggled in ahead of the host', () => {
    // The one that got through the first version of this guard, and the reason it now asks
    // the URL parser instead of matching strings. The WHATWG parser strips ASCII tab and
    // newline BEFORE parsing, so each of these is `//evil.example` by the time a browser
    // looks at it - while a string check sees one leading slash and waves it through.
    // Reachable as `?next=/%09/evil.example`, which URLSearchParams decodes for us.
    expect(safeReturnPath('/\t/evil.example')).toBeNull()
    expect(safeReturnPath('/\n/evil.example')).toBeNull()
    expect(safeReturnPath('/\r/evil.example')).toBeNull()
  })

  it('returns the normalised path, not the caller string', () => {
    // Handing back the raw value would let the sink re-parse it and reach a different
    // conclusion from the one this function just approved - which is the whole bug above.
    expect(safeReturnPath('/docs/../chores')).toBe('/chores')
    expect(safeReturnPath('/docs#operations')).toBe('/docs#operations')
  })

  it('rejects an over-long path rather than truncating it', () => {
    // A truncated path is a *different* path, so sending somebody to a mangled url would be
    // worse than sending them home, which is where null lands them.
    expect(safeReturnPath(`/${'a'.repeat(255)}`)).toBeNull()
    // Exactly at the cap is allowed; without this, `>` and `>=` are indistinguishable.
    expect(safeReturnPath(`/${'a'.repeat(254)}`)).toBe(`/${'a'.repeat(254)}`)
  })

  it('measures the cap against the normalised path, which can be longer', () => {
    // Percent-encoding lengthens: each space becomes %20. An input under the cap can leave
    // over it, and the cap exists to match the 255-char column the backend stores this in
    // when it rides on to SSO - so it is the *returned* value that has to fit.
    // Interior spaces, not trailing ones - the parser strips trailing whitespace, so a
    // fixture using it shortens instead of lengthening and proves nothing.
    const spaced = `/${Array(85).fill('a').join(' ')}`
    expect(spaced.length).toBeLessThanOrEqual(255)
    expect(safeReturnPath(spaced)).toBeNull()
  })

  it('rejects nothing at all', () => {
    expect(safeReturnPath(null)).toBeNull()
    expect(safeReturnPath(undefined)).toBeNull()
    expect(safeReturnPath('')).toBeNull()
  })

  it('rejects a bare path with no leading slash', () => {
    // `evil.example/x` is relative to the current directory in a browser, but it is also
    // what a careless caller would pass meaning a host - discarded either way.
    expect(safeReturnPath('docs')).toBeNull()
  })
})
