import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import '@fontsource-variable/bricolage-grotesque/index.css'
import '@fontsource-variable/manrope/index.css'
import './index.css'
import './i18n/i18n'
import App from './App'
import AuthProvider from './auth/AuthProvider'
import ThemeProvider from './theme/ThemeProvider'
import ErrorBoundary from './components/ErrorBoundary'
import { Toaster } from './components/ui/sonner'
import { registerServiceWorker } from './pwa'

registerServiceWorker()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      {/* App-wide safety net: a render error (or a failed lazy-route chunk load)
          shows a recoverable reload screen instead of a blank page. */}
      <ErrorBoundary>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </ErrorBoundary>
      <Toaster />
    </ThemeProvider>
  </StrictMode>,
)
