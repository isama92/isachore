import { describe, expect, it } from 'vitest'
import { routes } from './routes'

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
