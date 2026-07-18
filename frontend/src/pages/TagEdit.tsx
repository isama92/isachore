import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { api, ApiError } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { TagForm } from '@/components/tags/TagForm'
import type { Tag } from '../lib/types'

export default function TagEdit() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { id = '' } = useParams()
  const [tag, setTag] = useState<Tag | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<Tag>(endpoints.tags.byId(id))
      .then((data) => {
        if (!cancelled) setTag(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('tagEdit.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id, t])

  async function handleSubmit(name: string, color: string) {
    await api.patch<Tag>(endpoints.tags.byId(id), { name, color })
    toast.success(t('tagEdit.updated'))
    await navigate('/tags')
  }

  return (
    <main className="mx-auto w-full max-w-lg px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">{t('tagEdit.title')}</h1>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : !tag ? (
        <p className="text-[13px] font-bold text-danger">{error ?? t('tagEdit.notFound')}</p>
      ) : (
        <TagForm
          initialName={tag.name}
          initialColor={tag.color}
          submitLabel={t('tagEdit.submit')}
          cancelTo="/tags"
          errorMessage={t('tagEdit.updateError')}
          onSubmit={handleSubmit}
        />
      )}
    </main>
  )
}
