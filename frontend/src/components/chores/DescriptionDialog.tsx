import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '@/i18n/i18n'
import { api, ApiError } from '@/lib/api'
import type { Chore } from '@/lib/types'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import RichText from '@/components/rich-text/RichText'

// Fetches and renders one chore's instructions. Split out from the dialog purely so the dialog
// can mount it with `key={chore.id}`: a fresh mount is what resets the loading state between two
// chores, which is otherwise a setHtml(null) in the effect body and exactly what
// react-hooks/set-state-in-effect forbids (see AuthProvider for the same rule).
function DescriptionBody({ choreId }: { choreId: number }) {
  const { t } = useTranslation()
  const [html, setHtml] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // State is only ever set inside the promise chain. `cancelled` guards the dialog being closed
    // before the response lands, which would otherwise set state on an unmounted body.
    let cancelled = false
    api
      .get<Chore>(`/api/v1/chores/${choreId}`)
      .then((full) => {
        if (!cancelled) setHtml(full.description ?? '')
      })
      .catch((e: unknown) => {
        // Read through the i18n singleton rather than the render-time `t`. Closing over `t` puts
        // it in the dependency list, so switching language with the dialog open would refetch the
        // chore for nothing. (Profile's language toast reaches for `i18n.t` too, for the
        // mirror-image reason: there it is to get the *new* language, here to shed a dependency.)
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : i18n.t('descriptionDialog.loadError'))
        }
      })
    return () => {
      cancelled = true
    }
  }, [choreId])

  if (error !== null) return <p className="text-[13px] font-bold text-danger">{error}</p>
  if (html === null) return <Spinner label={t('descriptionDialog.loading')} />
  // Only reachable if the description was cleared between the list loading and the dialog
  // opening: without has_description the row renders no marker to click.
  if (html === '')
    return (
      <p className="text-sm font-medium text-muted-foreground">{t('descriptionDialog.empty')}</p>
    )
  return <RichText html={html} />
}

// "What am I supposed to do?" - the chore's written instructions, readable from the two list pages
// without detouring through the chore management pages. Shared by both, and opened by `chore`
// being non-null, exactly like CreditDialog beside it.
//
// A Dialog rather than an AlertDialog: this is the app's first purely informational dialog, with
// nothing to confirm and nothing to cancel. DialogContent supplies the close X.
//
// The description is fetched on open rather than carried in the list payload, so a household's
// instructions never ride along on the landing page's response. The cost is the loading and error
// states above; there is no cache, because a description can change between two opens and one
// request is cheaper than reasoning about staleness.
export default function DescriptionDialog({
  chore,
  onClose,
}: {
  // id and title both come from the row, so the heading is correct before the fetch resolves.
  chore: { id: number; title: string } | null
  onClose: () => void
}) {
  const bodyId = useId()
  return (
    <Dialog open={chore !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg" aria-describedby={bodyId}>
        <DialogHeader>
          <DialogTitle>{chore?.title ?? ''}</DialogTitle>
        </DialogHeader>
        {/* No DialogDescription: it renders a <p>, and the rendered rich text has <p> and <ul> of
            its own, which cannot legally nest inside one. DialogContent is pointed at this div
            instead, so the dialog is still described by its content. */}
        {/* No DialogFooter: DialogContent already renders a close X, and a second "Close" in the
            footer gave two buttons with the same accessible name for the same action. There is
            nothing to confirm here, so the X plus Escape plus clicking the overlay is the whole
            interaction. */}
        <div id={bodyId} className="max-h-[60vh] overflow-y-auto">
          {chore && <DescriptionBody key={chore.id} choreId={chore.id} />}
        </div>
      </DialogContent>
    </Dialog>
  )
}
