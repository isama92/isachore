import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../../auth/useAuth'
import { api, ApiError } from '../../lib/api'
import type { User } from '../../lib/types'

type FormState = {
  email: string
  name: string
  password: string
  is_admin: boolean
}

const emptyForm: FormState = { email: '', name: '', password: '', is_admin: false }

const inputClass =
  'rounded-input border-[1.5px] border-line bg-white px-4 py-2.5 text-[15px] font-semibold placeholder:font-medium placeholder:text-placeholder focus:border-primary focus:outline-none'
const labelClass = 'text-[11.5px] font-bold tracking-wide text-muted uppercase'

export default function Users() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [saving, setSaving] = useState(false)

  const load = useCallback(
    () =>
      api
        .get<User[]>('/api/v1/users')
        .then((data) => setUsers(data))
        .catch((err: unknown) => {
          setError(err instanceof ApiError ? err.message : 'Failed to load users')
        })
        .finally(() => setLoading(false)),
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  function openCreate() {
    setEditing(null)
    setForm(emptyForm)
    setShowForm(true)
    setError(null)
  }

  function openEdit(u: User) {
    setEditing(u)
    setForm({ email: u.email, name: u.name, password: '', is_admin: u.is_admin })
    setShowForm(true)
    setError(null)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (editing) {
        const payload: Record<string, unknown> = {
          email: form.email,
          name: form.name,
          is_admin: form.is_admin,
        }
        if (form.password) payload.password = form.password
        await api.patch<User>(`/api/v1/users/${editing.id}`, payload)
      } else {
        await api.post<User>('/api/v1/users', form)
      }
      setShowForm(false)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Saving failed')
    } finally {
      setSaving(false)
    }
  }

  async function setActive(u: User, active: boolean) {
    if (
      !active &&
      !window.confirm(`Deactivate ${u.name}? They will be logged out and unable to sign in.`)
    ) {
      return
    }
    setError(null)
    try {
      if (active) {
        await api.patch<User>(`/api/v1/users/${u.id}`, { is_active: true })
      } else {
        await api.del(`/api/v1/users/${u.id}`)
      }
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Update failed')
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-5 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="font-display text-2xl font-bold tracking-tight">Users</h1>
        <button
          onClick={openCreate}
          className="rounded-button bg-primary px-4 py-2 text-sm font-extrabold text-white shadow-glow hover:bg-primary-dark"
        >
          Add user
        </button>
      </div>

      {error && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}

      {showForm && (
        <form
          onSubmit={(e) => void onSubmit(e)}
          className="mb-6 flex flex-col gap-4 rounded-2xl border border-line bg-white p-5"
        >
          <h2 className="font-display text-lg font-bold tracking-tight">
            {editing ? `Edit ${editing.name}` : 'New user'}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className={labelClass}>Name</span>
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className={inputClass}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className={labelClass}>Email</span>
              <input
                type="email"
                required
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                className={inputClass}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className={labelClass}>Password</span>
              <input
                type="password"
                required={!editing}
                minLength={8}
                placeholder={editing ? 'Leave empty to keep current' : 'At least 8 characters'}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                className={inputClass}
              />
            </label>
            <label className="flex items-center gap-2.5 self-end pb-3">
              <input
                type="checkbox"
                checked={form.is_admin}
                disabled={editing?.id === me?.id}
                onChange={(e) => setForm({ ...form, is_admin: e.target.checked })}
                className="size-4 accent-(--color-primary)"
              />
              <span className="text-sm font-bold text-ink">Admin</span>
            </label>
          </div>
          <div className="flex gap-3">
            <button
              type="submit"
              disabled={saving}
              className="rounded-button bg-primary px-5 py-2.5 text-sm font-extrabold text-white shadow-glow hover:bg-primary-dark disabled:opacity-60"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-button px-5 py-2.5 text-sm font-bold text-muted hover:text-ink"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="font-medium text-muted">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-line bg-white">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-[11.5px] font-bold tracking-wide text-muted uppercase">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-3 font-semibold">
                    {u.name}
                    {u.id === me?.id && (
                      <span className="ml-2 text-[11px] font-bold text-placeholder">you</span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-medium text-muted">{u.email}</td>
                  <td className="px-4 py-3">
                    {u.is_admin && (
                      <span className="mr-1.5 rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-bold text-primary-dark">
                        Admin
                      </span>
                    )}
                    {u.is_active ? (
                      <span className="rounded-full bg-page px-2.5 py-0.5 text-[11px] font-bold text-primary-dark">
                        Active
                      </span>
                    ) : (
                      <span className="rounded-full bg-canvas px-2.5 py-0.5 text-[11px] font-bold text-muted">
                        Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <button
                      onClick={() => openEdit(u)}
                      className="font-bold text-primary hover:text-primary-dark"
                    >
                      Edit
                    </button>
                    {u.id !== me?.id &&
                      (u.is_active ? (
                        <button
                          onClick={() => void setActive(u, false)}
                          className="ml-3 font-bold text-danger hover:opacity-80"
                        >
                          Deactivate
                        </button>
                      ) : (
                        <button
                          onClick={() => void setActive(u, true)}
                          className="ml-3 font-bold text-primary hover:text-primary-dark"
                        >
                          Reactivate
                        </button>
                      ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  )
}
