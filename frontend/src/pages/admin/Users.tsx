import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useAuth } from '../../auth/useAuth'
import { api, ApiError } from '../../lib/api'
import type { User } from '../../lib/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

type FormState = {
  email: string
  name: string
  password: string
  is_admin: boolean
  is_active: boolean
}

const emptyForm: FormState = {
  email: '',
  name: '',
  password: '',
  is_admin: false,
  is_active: true,
}

export default function Users() {
  const { user: me, refresh } = useAuth()
  const navigate = useNavigate()
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
    setForm({
      email: u.email,
      name: u.name,
      password: '',
      is_admin: u.is_admin,
      is_active: u.is_active,
    })
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
          is_active: form.is_active,
        }
        if (form.password) payload.password = form.password
        await api.patch<User>(`/api/v1/users/${editing.id}`, payload)
      } else {
        await api.post<User>('/api/v1/users', form)
      }
      toast.success(editing ? 'User updated' : 'User created')
      setShowForm(false)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Saving failed')
    } finally {
      setSaving(false)
    }
  }

  async function loginAs(u: User) {
    setError(null)
    try {
      await api.post<User>(`/api/v1/users/${u.id}/impersonate`)
      toast.success(`Viewing as ${u.name}`)
      await refresh()
      await navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not log in as this user')
    }
  }

  async function setActive(u: User, active: boolean) {
    setError(null)
    try {
      if (active) {
        await api.patch<User>(`/api/v1/users/${u.id}`, { is_active: true })
      } else {
        await api.del(`/api/v1/users/${u.id}`)
      }
      toast.success(active ? 'User reactivated' : 'User deactivated')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Update failed')
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-5 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="font-display text-2xl font-bold tracking-tight">Users</h1>
        <Button type="button" size="lg" onClick={openCreate}>
          Add user
        </Button>
      </div>

      {error && !showForm && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}

      <Dialog
        open={showForm}
        onOpenChange={(open) => {
          setShowForm(open)
          if (!open) setError(null)
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-4">
            <DialogHeader>
              <DialogTitle>{editing ? `Edit ${editing.name}` : 'New user'}</DialogTitle>
              <DialogDescription className="sr-only">
                {editing ? 'Update this account.' : 'Create a new household member.'}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="user-name">Name</Label>
                <Input
                  id="user-name"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="user-email">Email</Label>
                <Input
                  id="user-email"
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="user-password">Password</Label>
                <Input
                  id="user-password"
                  type="password"
                  required={!editing}
                  minLength={8}
                  placeholder={editing ? 'Leave empty to keep current' : 'At least 8 characters'}
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                />
              </div>
              <div className="flex items-center gap-5 self-end pb-3">
                <div className="flex items-center gap-2.5">
                  <Checkbox
                    id="is-admin"
                    checked={form.is_admin}
                    disabled={editing?.id === me?.id}
                    onCheckedChange={(v) => setForm({ ...form, is_admin: v === true })}
                  />
                  <Label
                    htmlFor="is-admin"
                    className="text-sm font-bold tracking-normal text-foreground normal-case"
                  >
                    Admin
                  </Label>
                </div>
                {editing && (
                  <div className="flex items-center gap-2.5">
                    <Checkbox
                      id="is-active"
                      checked={form.is_active}
                      disabled={editing.id === me?.id}
                      onCheckedChange={(v) => setForm({ ...form, is_active: v === true })}
                    />
                    <Label
                      htmlFor="is-active"
                      className="text-sm font-bold tracking-normal text-foreground normal-case"
                    >
                      Active
                    </Label>
                  </div>
                )}
              </div>
            </div>
            {error && <p className="text-[13px] font-bold text-danger">{error}</p>}
            <DialogFooter>
              <Button type="button" variant="ghost" size="lg" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
              <Button type="submit" size="lg" disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {loading ? (
        <p className="font-medium text-muted-foreground">Loading…</p>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-line bg-card">
          <Table className="min-w-[640px]">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-semibold">
                    {u.name}
                    {u.id === me?.id && (
                      <span className="ml-2 text-[11px] font-bold text-placeholder">you</span>
                    )}
                  </TableCell>
                  <TableCell className="font-medium text-muted-foreground">{u.email}</TableCell>
                  <TableCell>
                    {u.is_admin ? (
                      <Badge variant="secondary" className="text-primary">
                        Admin
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="text-muted-foreground">
                        Member
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {u.is_active ? (
                      <Badge variant="secondary" className="text-primary">
                        Active
                      </Badge>
                    ) : (
                      <Badge variant="destructive">Inactive</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {u.id !== me?.id && u.is_active && (
                      <Button
                        type="button"
                        variant="link"
                        size="sm"
                        className="mr-3 h-auto p-0 font-bold text-muted-foreground hover:text-foreground hover:no-underline"
                        onClick={() => void loginAs(u)}
                      >
                        Login as
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="link"
                      size="sm"
                      className="h-auto p-0 font-bold hover:text-primary-dark hover:no-underline"
                      onClick={() => openEdit(u)}
                    >
                      Edit
                    </Button>
                    {u.id !== me?.id &&
                      (u.is_active ? (
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              type="button"
                              variant="link"
                              size="sm"
                              className="ml-3 h-auto p-0 font-bold text-destructive hover:no-underline hover:opacity-80"
                            >
                              Deactivate
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Deactivate {u.name}?</AlertDialogTitle>
                              <AlertDialogDescription>
                                They will be logged out and unable to sign in.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction
                                variant="destructive"
                                onClick={() => void setActive(u, false)}
                              >
                                Deactivate user
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      ) : (
                        <Button
                          type="button"
                          variant="link"
                          size="sm"
                          className="ml-3 h-auto p-0 font-bold hover:text-primary-dark hover:no-underline"
                          onClick={() => void setActive(u, true)}
                        >
                          Reactivate
                        </Button>
                      ))}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </main>
  )
}
