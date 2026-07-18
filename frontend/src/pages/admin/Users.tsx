import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import type { ColumnDef } from '@tanstack/react-table'
import { LogInIcon, SendIcon, SquarePenIcon, UserCheckIcon, UserXIcon } from 'lucide-react'
import { useAuth } from '../../auth/useAuth'
import { api, ApiError } from '../../lib/api'
import { formatDateTime, formatDateTimeFull } from '../../lib/format'
import { fullName } from '../../lib/user'
import type { ServerSettings, User, UserStatus } from '../../lib/types'
import { DataTable } from '@/components/data-table/DataTable'
import { useServerTable } from '@/components/data-table/useServerTable'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

type FormState = {
  email: string
  first_name: string
  last_name: string
  password: string
  is_admin: boolean
  status: UserStatus
}

const emptyForm: FormState = {
  email: '',
  first_name: '',
  last_name: '',
  password: '',
  is_admin: false,
  status: 'active',
}

type UserFilters = {
  name: string
  email: string
  status: string
  role: string
}

// Radix Select forbids an empty-string value, so the "all" option uses this
// sentinel and maps to '' (unset) when written to the table filter.
const ALL = 'all'

export default function Users() {
  const { user: me, refresh } = useAuth()
  const { t } = useTranslation()
  const navigate = useNavigate()

  const table = useServerTable<User, UserFilters>({
    endpoint: '/api/v1/users',
    initial: {
      sortBy: 'created_at',
      sortDir: 'desc',
      pageSize: 20,
      filters: { name: '', email: '', status: 'active', role: '' },
    },
  })

  const [settings, setSettings] = useState<ServerSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [saving, setSaving] = useState(false)

  // Local text-filter state for instant typing feedback; pushed to the table
  // (which refetches) after a short debounce.
  const [nameInput, setNameInput] = useState(table.filters.name)
  const [emailInput, setEmailInput] = useState(table.filters.email)

  // When confirmation is required, new users set their own password via an
  // emailed link, so the create form hides the password field.
  const requireConfirmation = settings?.require_confirmation ?? false
  const smtpConfigured = settings?.smtp_configured ?? false

  useEffect(() => {
    void api
      .get<ServerSettings>('/api/v1/settings')
      .then((data) => setSettings(data))
      .catch(() => setSettings(null))
  }, [])

  // Keep a latest-value ref to the (per-render) setFilter so the debounce
  // effects don't need it as a dependency (which would reset the timer every
  // render). Updated after commit, never synchronously during render.
  const setFilterRef = useRef(table.setFilter)
  useEffect(() => {
    setFilterRef.current = table.setFilter
  })

  useEffect(() => {
    const id = setTimeout(() => setFilterRef.current('name', nameInput.trim()), 300)
    return () => clearTimeout(id)
  }, [nameInput])

  useEffect(() => {
    const id = setTimeout(() => setFilterRef.current('email', emailInput.trim()), 300)
    return () => clearTimeout(id)
  }, [emailInput])

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
      status: u.status,
    })
    setShowForm(true)
    setError(null)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const payload: Record<string, unknown> = {
        email: form.email,
        first_name: form.first_name,
        last_name: form.last_name,
        is_admin: form.is_admin,
      }
      if (editing) {
        payload.status = form.status
        if (form.password) payload.password = form.password
        await api.patch<User>(`/api/v1/users/${editing.id}`, payload)
      } else {
        // With confirmation on, the password field is hidden and the user sets
        // it via the emailed link; otherwise the admin's password is required.
        if (!requireConfirmation) payload.password = form.password
        await api.post<User>('/api/v1/users', payload)
      }
      toast.success(editing ? t('users.toastUpdated') : t('users.toastCreated'))
      setShowForm(false)
      table.reload()
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
        // A never-confirmed user has no usable password, so reactivating them
        // sends them back to waiting_confirmation (the server resends the email)
        // rather than active.
        const status: UserStatus = u.confirmed_at ? 'active' : 'waiting_confirmation'
        await api.patch<User>(`/api/v1/users/${u.id}`, { status })
      } else {
        await api.del(`/api/v1/users/${u.id}`)
      }
      toast.success(active ? t('users.reactivated') : t('users.deactivated'))
      table.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('users.updateError'))
    }
  }

  async function resendConfirmation(u: User) {
    setError(null)
    try {
      await api.post(`/api/v1/users/${u.id}/resend-confirmation`)
      toast.success(t('users.resent', { name: fullName(u) }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('users.resendError'))
    }
  }

  function statusBadge(u: User) {
    if (u.status === 'active') {
      // Active but never confirmed (an admin forced it while confirmation is on)
      // is surfaced in the warning colour so it stands out from a normal active.
      const unconfirmed = requireConfirmation && !u.confirmed_at
      return (
        <Badge variant="secondary" className={unconfirmed ? 'text-warning' : 'text-primary'}>
          {t('users.statusActive')}
        </Badge>
      )
    }
    if (u.status === 'waiting_confirmation') {
      return (
        <Badge variant="secondary" className="text-warning">
          {t('users.statusWaiting')}
        </Badge>
      )
    }
    return <Badge variant="destructive">{t('users.statusDisabled')}</Badge>
  }

  function iconAction(label: string, icon: ReactNode, onClick: () => void, danger = false) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            className={danger ? 'text-destructive hover:text-destructive' : undefined}
            onClick={onClick}
          >
            {icon}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    )
  }

  function deactivateReactivate(u: User) {
    const disabling = u.status !== 'disabled'
    const label = disabling ? t('users.deactivate') : t('users.reactivate')
    return (
      <AlertDialog>
        <Tooltip>
          <TooltipTrigger asChild>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={label}
                className={disabling ? 'text-destructive hover:text-destructive' : undefined}
              >
                {disabling ? <UserXIcon /> : <UserCheckIcon />}
              </Button>
            </AlertDialogTrigger>
          </TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {disabling
                ? t('users.deactivateConfirm', { name: fullName(u) })
                : t('users.reactivateConfirm', { name: fullName(u) })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {disabling ? t('users.deactivateBody') : t('users.reactivateBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant={disabling ? 'destructive' : 'default'}
              onClick={() => void setActive(u, !disabling)}
            >
              {disabling ? t('users.deactivateAction') : t('users.reactivateAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  function rowActions(u: User) {
    const isSelf = u.id === me?.id
    return (
      <div className="flex items-center justify-end gap-0.5">
        {!isSelf &&
          u.status === 'active' &&
          iconAction(t('users.loginAs'), <LogInIcon />, () => void loginAs(u))}
        {!isSelf &&
          u.status === 'waiting_confirmation' &&
          smtpConfigured &&
          iconAction(t('users.resend'), <SendIcon />, () => void resendConfirmation(u))}
        {iconAction(t('users.edit'), <SquarePenIcon />, () => openEdit(u))}
        {!isSelf && deactivateReactivate(u)}
      </div>
    )
  }

  const columns: ColumnDef<User>[] = [
    {
      accessorKey: 'id',
      header: t('users.headers.id'),
      meta: {
        headClassName: 'w-16',
        cellClassName: 'font-medium text-muted-foreground tabular-nums',
      },
    },
    {
      id: 'name',
      // accessorFn (unused for display, the cell renders below) makes this a
      // sortable column; the actual ordering is done server-side by sort_by=name.
      accessorFn: (u) => fullName(u),
      header: t('users.headers.name'),
      cell: ({ row }) => (
        <span className="font-semibold">
          {fullName(row.original)}
          {row.original.id === me?.id && (
            <span className="ml-2 text-[11px] font-bold text-placeholder">{t('users.you')}</span>
          )}
        </span>
      ),
    },
    {
      accessorKey: 'email',
      header: t('users.headers.email'),
      meta: { cellClassName: 'font-medium text-muted-foreground' },
    },
    {
      id: 'role',
      header: t('users.headers.role'),
      enableSorting: false,
      cell: ({ row }) =>
        row.original.is_admin ? (
          <Badge variant="secondary" className="text-primary">
            {t('users.roleAdmin')}
          </Badge>
        ) : (
          <Badge variant="secondary" className="text-muted-foreground">
            {t('users.roleMember')}
          </Badge>
        ),
    },
    {
      id: 'status',
      header: t('users.headers.status'),
      enableSorting: false,
      cell: ({ row }) => statusBadge(row.original),
    },
    {
      accessorKey: 'created_at',
      header: t('users.headers.createdAt'),
      cell: ({ row }) => (
        <span title={formatDateTimeFull(row.original.created_at)}>
          {formatDateTime(row.original.created_at)}
        </span>
      ),
      meta: { cellClassName: 'text-muted-foreground' },
    },
    {
      id: 'actions',
      header: t('users.headers.actions'),
      enableSorting: false,
      cell: ({ row }) => rowActions(row.original),
      meta: { headClassName: 'text-right', cellClassName: 'text-right' },
    },
  ]

  const showPasswordField = editing !== null || !requireConfirmation

  return (
    <TooltipProvider>
      <main className="mx-auto w-full max-w-6xl px-5 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="font-display text-2xl font-bold tracking-tight">{t('users.title')}</h1>
          <Button type="button" size="lg" onClick={openCreate}>
            {t('users.addUser')}
          </Button>
        </div>

        {!showForm && (error || table.error) && (
          <p className="mb-4 text-[13px] font-bold text-danger">{error ?? t('users.loadError')}</p>
        )}

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
                {showPasswordField ? (
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
                ) : (
                  <p className="self-end pb-2.5 text-[13px] font-medium text-muted-foreground">
                    {t('users.passwordViaEmail')}
                  </p>
                )}
                <div className="flex items-center gap-2.5 self-end pb-3">
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
              </div>
              {editing && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="user-status">{t('users.statusLabel')}</Label>
                  <Select
                    value={form.status}
                    disabled={editing.id === me?.id}
                    onValueChange={(v) => setForm({ ...form, status: v as UserStatus })}
                  >
                    <SelectTrigger id="user-status" className="w-full sm:w-72">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {/* Waiting needs an email to be useful; only offer it when
                          SMTP is configured, or when the user is already in it. */}
                      {(smtpConfigured || editing.status === 'waiting_confirmation') && (
                        <SelectItem value="waiting_confirmation">
                          {t('users.statusWaiting')}
                        </SelectItem>
                      )}
                      <SelectItem value="active">{t('users.statusActive')}</SelectItem>
                      <SelectItem value="disabled">{t('users.statusDisabled')}</SelectItem>
                    </SelectContent>
                  </Select>
                  {requireConfirmation && form.status === 'active' && !editing.confirmed_at && (
                    <p className="text-[13px] font-bold text-warning">
                      {t('users.confirmWarning')}
                    </p>
                  )}
                </div>
              )}
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

        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <Input
            className="sm:w-56"
            placeholder={t('users.filters.namePlaceholder')}
            aria-label={t('users.filters.namePlaceholder')}
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
          />
          <Input
            className="sm:w-56"
            placeholder={t('users.filters.emailPlaceholder')}
            aria-label={t('users.filters.emailPlaceholder')}
            value={emailInput}
            onChange={(e) => setEmailInput(e.target.value)}
          />
          <Select
            value={table.filters.status || ALL}
            onValueChange={(v) => table.setFilter('status', v === ALL ? '' : v)}
          >
            <SelectTrigger className="sm:w-44" aria-label={t('users.headers.status')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('users.filters.statusAll')}</SelectItem>
              <SelectItem value="active">{t('users.statusActive')}</SelectItem>
              <SelectItem value="waiting_confirmation">{t('users.statusWaiting')}</SelectItem>
              <SelectItem value="disabled">{t('users.statusDisabled')}</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={table.filters.role || ALL}
            onValueChange={(v) => table.setFilter('role', v === ALL ? '' : v)}
          >
            <SelectTrigger className="sm:w-40" aria-label={t('users.headers.role')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('users.filters.roleAll')}</SelectItem>
              <SelectItem value="admins">{t('users.roleAdmin')}</SelectItem>
              <SelectItem value="members">{t('users.roleMember')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <DataTable columns={columns} table={table} minWidthClassName="min-w-[860px]" />
      </main>
    </TooltipProvider>
  )
}
