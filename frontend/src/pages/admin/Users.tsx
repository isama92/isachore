import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useAuth } from '../../auth/useAuth'
import { api, ApiError } from '../../lib/api'
import { fullName } from '../../lib/user'
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
  first_name: string
  last_name: string
  password: string
  is_admin: boolean
  is_active: boolean
}

const emptyForm: FormState = {
  email: '',
  first_name: '',
  last_name: '',
  password: '',
  is_admin: false,
  is_active: true,
}

export default function Users() {
  const { user: me, refresh } = useAuth()
  const { t } = useTranslation()
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
          setError(err instanceof ApiError ? err.message : t('users.loadError'))
        })
        .finally(() => setLoading(false)),
    [t],
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
      first_name: u.first_name,
      last_name: u.last_name,
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
          first_name: form.first_name,
          last_name: form.last_name,
          is_admin: form.is_admin,
          is_active: form.is_active,
        }
        if (form.password) payload.password = form.password
        await api.patch<User>(`/api/v1/users/${editing.id}`, payload)
      } else {
        await api.post<User>('/api/v1/users', form)
      }
      toast.success(editing ? t('users.toastUpdated') : t('users.toastCreated'))
      setShowForm(false)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('users.saveError'))
    } finally {
      setSaving(false)
    }
  }

  async function loginAs(u: User) {
    setError(null)
    try {
      await api.post<User>(`/api/v1/users/${u.id}/impersonate`)
      toast.success(t('users.viewingAs', { name: fullName(u) }))
      await refresh()
      await navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('users.loginAsError'))
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
      toast.success(active ? t('users.reactivated') : t('users.deactivated'))
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('users.updateError'))
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-5 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="font-display text-2xl font-bold tracking-tight">{t('users.title')}</h1>
        <Button type="button" size="lg" onClick={openCreate}>
          {t('users.addUser')}
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
              <DialogTitle>
                {editing ? t('users.editTitle', { name: fullName(editing) }) : t('users.newUser')}
              </DialogTitle>
              <DialogDescription className="sr-only">
                {editing ? t('users.editDescription') : t('users.newDescription')}
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="user-first-name">{t('common.firstName')}</Label>
                <Input
                  id="user-first-name"
                  required
                  value={form.first_name}
                  onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="user-last-name">{t('common.lastName')}</Label>
                <Input
                  id="user-last-name"
                  required
                  value={form.last_name}
                  onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="user-email">{t('common.email')}</Label>
                <Input
                  id="user-email"
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="user-password">{t('common.password')}</Label>
                <Input
                  id="user-password"
                  type="password"
                  required={!editing}
                  minLength={8}
                  placeholder={editing ? t('users.passwordKeep') : t('common.passwordMin')}
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
                    {t('users.adminLabel')}
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
                      {t('users.activeLabel')}
                    </Label>
                  </div>
                )}
              </div>
            </div>
            {error && <p className="text-[13px] font-bold text-danger">{error}</p>}
            <DialogFooter>
              <Button type="button" variant="ghost" size="lg" onClick={() => setShowForm(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" size="lg" disabled={saving}>
                {saving ? t('common.saving') : t('common.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-line bg-card">
          <Table className="min-w-[640px]">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>{t('users.headers.name')}</TableHead>
                <TableHead>{t('users.headers.email')}</TableHead>
                <TableHead>{t('users.headers.role')}</TableHead>
                <TableHead>{t('users.headers.status')}</TableHead>
                <TableHead className="text-right">{t('users.headers.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-semibold">
                    {fullName(u)}
                    {u.id === me?.id && (
                      <span className="ml-2 text-[11px] font-bold text-placeholder">
                        {t('users.you')}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="font-medium text-muted-foreground">{u.email}</TableCell>
                  <TableCell>
                    {u.is_admin ? (
                      <Badge variant="secondary" className="text-primary">
                        {t('users.roleAdmin')}
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="text-muted-foreground">
                        {t('users.roleMember')}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {u.is_active ? (
                      <Badge variant="secondary" className="text-primary">
                        {t('users.statusActive')}
                      </Badge>
                    ) : (
                      <Badge variant="destructive">{t('users.statusInactive')}</Badge>
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
                        {t('users.loginAs')}
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="link"
                      size="sm"
                      className="h-auto p-0 font-bold hover:text-primary-dark hover:no-underline"
                      onClick={() => openEdit(u)}
                    >
                      {t('users.edit')}
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
                              {t('users.deactivate')}
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>
                                {t('users.deactivateConfirm', { name: fullName(u) })}
                              </AlertDialogTitle>
                              <AlertDialogDescription>
                                {t('users.deactivateBody')}
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                              <AlertDialogAction
                                variant="destructive"
                                onClick={() => void setActive(u, false)}
                              >
                                {t('users.deactivateAction')}
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      ) : (
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              type="button"
                              variant="link"
                              size="sm"
                              className="ml-3 h-auto p-0 font-bold hover:text-primary-dark hover:no-underline"
                            >
                              {t('users.reactivate')}
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>
                                {t('users.reactivateConfirm', { name: fullName(u) })}
                              </AlertDialogTitle>
                              <AlertDialogDescription>
                                {t('users.reactivateBody')}
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                              <AlertDialogAction onClick={() => void setActive(u, true)}>
                                {t('users.reactivateAction')}
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
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
