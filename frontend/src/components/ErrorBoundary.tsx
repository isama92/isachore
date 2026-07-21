import { Component, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

// The default full-page fallback: a title, a hint, and a reload button. Reload is
// the reliable recovery for a crashed render or a failed lazy-chunk download (it
// refetches the current assets). react-i18next reads the i18n singleton directly
// (there is no I18nextProvider in the tree), so this renders even when the crashed
// subtree included the app's own providers.
function DefaultErrorFallback() {
  const { t } = useTranslation()
  return (
    <main className="mx-auto flex min-h-svh w-full max-w-md flex-col items-center justify-center gap-3 px-5 text-center">
      <h1 className="font-display text-lg font-bold tracking-tight">{t('common.errorTitle')}</h1>
      <p className="font-medium text-muted-foreground">{t('common.errorHint')}</p>
      <Button type="button" className="mt-2" onClick={() => window.location.reload()}>
        {t('common.reload')}
      </Button>
    </main>
  )
}

type Props = { children: ReactNode; fallback?: ReactNode }
type State = { hasError: boolean }

// App-wide error boundary. React error boundaries must be class components; this
// catches render errors (and failed lazy-route chunk loads) anywhere in its
// subtree and shows a recoverable fallback instead of letting the error unmount
// the whole app. Pass `fallback` to override the default full-page message.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  render(): ReactNode {
    if (this.state.hasError) return this.props.fallback ?? <DefaultErrorFallback />
    return this.props.children
  }
}
