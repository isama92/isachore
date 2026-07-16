import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, ApiError } from '../lib/api'
import { assignmentOptions, repeatOptions, todayISO } from '../lib/chores'
import type { AssignmentType, Chore, Household, RepeatPeriod, Tag, User } from '../lib/types'

type FormState = {
  title: string
  description: string
  start_date: string
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  assignee_ids: number[]
  tag_ids: number[]
}

const inputClass =
  'rounded-input border-[1.5px] border-line bg-white px-4 py-2.5 text-[15px] font-semibold placeholder:font-medium placeholder:text-placeholder focus:border-primary focus:outline-none'
const labelClass = 'text-[11.5px] font-bold tracking-wide text-muted uppercase'

function chipClass(selected: boolean): string {
  return `flex items-center gap-2 rounded-full border-[1.5px] px-3 py-1.5 text-sm font-bold ${
    selected
      ? 'border-primary bg-primary text-white'
      : 'border-line bg-white text-muted hover:border-primary'
  }`
}

export default function ChoreCreate() {
  const navigate = useNavigate()
  const [members, setMembers] = useState<User[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<FormState>(() => ({
    title: '',
    description: '',
    start_date: todayISO(),
    repeats: 'weekly',
    assignment_type: 'manual',
    assignee_ids: [],
    tag_ids: [],
  }))

  useEffect(() => {
    let cancelled = false
    Promise.all([api.get<Household[]>('/api/v1/households'), api.get<Tag[]>('/api/v1/tags')])
      .then(([households, tagList]) => {
        if (cancelled) return
        setMembers(households[0]?.members ?? [])
        setTags(tagList)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Failed to load the form')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function toggle(key: 'assignee_ids' | 'tag_ids', id: number) {
    setForm((f) => ({
      ...f,
      [key]: f[key].includes(id) ? f[key].filter((x) => x !== id) : [...f[key], id],
    }))
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await api.post<Chore>('/api/v1/chores', {
        title: form.title,
        description: form.description || null,
        start_date: form.start_date,
        repeats: form.repeats,
        assignment_type: form.assignment_type,
        assignee_ids: form.assignee_ids,
        tag_ids: form.tag_ids,
      })
      await navigate('/chores')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the chore')
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="mx-auto max-w-lg px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">New chore</h1>

      {loading ? (
        <p className="font-medium text-muted">Loading…</p>
      ) : (
        <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-5">
          <label className="flex flex-col gap-1.5">
            <span className={labelClass}>Title</span>
            <input
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="Clean the bathroom"
              className={inputClass}
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className={labelClass}>Notes</span>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Scrub the tub, replace the towels…"
              rows={3}
              className={inputClass}
            />
          </label>

          <div className="flex flex-col gap-2">
            <span className={labelClass}>Assignees</span>
            {members.length === 0 ? (
              <p className="text-sm font-medium text-muted">No household members yet.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {members.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => toggle('assignee_ids', m.id)}
                    aria-pressed={form.assignee_ids.includes(m.id)}
                    className={chipClass(form.assignee_ids.includes(m.id))}
                  >
                    {m.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className={labelClass}>Assignment</span>
              <select
                value={form.assignment_type}
                onChange={(e) =>
                  setForm({ ...form, assignment_type: e.target.value as AssignmentType })
                }
                className={inputClass}
              >
                {assignmentOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1.5">
              <span className={labelClass}>Repeats</span>
              <select
                value={form.repeats}
                onChange={(e) => setForm({ ...form, repeats: e.target.value as RepeatPeriod })}
                className={inputClass}
              >
                {repeatOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="flex flex-col gap-1.5">
            <span className={labelClass}>Start date</span>
            <input
              type="date"
              required
              value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
              className={inputClass}
            />
          </label>

          <div className="flex flex-col gap-2">
            <span className={labelClass}>Tags</span>
            {tags.length === 0 ? (
              <p className="text-sm font-medium text-muted">No tags yet.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {tags.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => toggle('tag_ids', t.id)}
                    aria-pressed={form.tag_ids.includes(t.id)}
                    className={chipClass(form.tag_ids.includes(t.id))}
                  >
                    <span
                      className="inline-block size-2.5 rounded-full"
                      style={{ backgroundColor: t.color }}
                    />
                    {t.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {error && <p className="text-[13px] font-bold text-danger">{error}</p>}

          <div className="flex gap-3">
            <button
              type="submit"
              disabled={saving}
              className="rounded-button bg-primary px-5 py-2.5 text-sm font-extrabold text-white shadow-glow hover:bg-primary-dark disabled:opacity-60"
            >
              {saving ? 'Saving…' : 'Add chore'}
            </button>
            <Link
              to="/chores"
              className="rounded-button px-5 py-2.5 text-sm font-bold text-muted hover:text-ink"
            >
              Cancel
            </Link>
          </div>
        </form>
      )}
    </main>
  )
}
