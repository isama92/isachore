import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { Route, Routes } from 'react-router'
import { routes } from './lib/routes'
import { Spinner } from '@/components/ui/spinner'
import RequireAdmin from './components/RequireAdmin'
import RequireAuth from './components/RequireAuth'
import AdminHouseholdCreate from './pages/admin/HouseholdCreate'
import AdminHouseholdEdit from './pages/admin/HouseholdEdit'
import AdminHouseholds from './pages/admin/Households'
import ServerSettings from './pages/admin/ServerSettings'
import UserCreate from './pages/admin/UserCreate'
import UserEdit from './pages/admin/UserEdit'
import Users from './pages/admin/Users'
import AcceptInvite from './pages/AcceptInvite'
import Chores from './pages/Chores'
import ConfirmAccount from './pages/ConfirmAccount'
import History from './pages/History'
import Home from './pages/Home'
import HouseholdCreate from './pages/HouseholdCreate'
import HouseholdEdit from './pages/HouseholdEdit'
import Households from './pages/Households'
import Login from './pages/Login'
import Profile from './pages/Profile'
import TagCreate from './pages/TagCreate'
import TagEdit from './pages/TagEdit'
import Tags from './pages/Tags'
import Unscheduled from './pages/Unscheduled'

// Two heavy dependencies, each confined to the handful of pages that need it and loaded on
// demand rather than in the initial bundle. Every other page stays eagerly imported.
//
// - Recharts, for Statistics.
// - Tiptap, for the chore form's rich text description. Only ChoreCreate and ChoreEdit reach
//   ChoreForm, so splitting the two of them is what keeps that chunk (~146 kB gzipped, more
//   than half the pre-Tiptap bundle) off every other route. This app is installed to phone home
//   screens, so the initial download is not a rounding error. If a third page ever renders
//   ChoreForm, it needs splitting too or the editor lands back in the main chunk.
const Statistics = lazy(() => import('./pages/Statistics'))
const ChoreCreate = lazy(() => import('./pages/ChoreCreate'))
const ChoreEdit = lazy(() => import('./pages/ChoreEdit'))

// Shown briefly while a split chunk downloads; the page then renders its own
// skeletons.
function RouteFallback() {
  const { t } = useTranslation()
  return (
    <main className="mx-auto flex w-full max-w-5xl items-center justify-center px-5 py-24">
      <Spinner size="lg" label={t('common.loading')} />
    </main>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path={routes.login} element={<Login />} />
      <Route path={routes.confirm} element={<ConfirmAccount />} />
      <Route path={routes.invite} element={<AcceptInvite />} />
      <Route element={<RequireAuth />}>
        <Route path={routes.home} element={<Home />} />
        <Route path={routes.unscheduled} element={<Unscheduled />} />
        <Route path={routes.profile} element={<Profile />} />
        <Route path={routes.chores.list} element={<Chores />} />
        <Route
          path={routes.chores.new}
          element={
            <Suspense fallback={<RouteFallback />}>
              <ChoreCreate />
            </Suspense>
          }
        />
        <Route
          path={routes.chores.edit.pattern}
          element={
            <Suspense fallback={<RouteFallback />}>
              <ChoreEdit />
            </Suspense>
          }
        />
        <Route path={routes.history} element={<History />} />
        <Route
          path={routes.statistics}
          element={
            <Suspense fallback={<RouteFallback />}>
              <Statistics />
            </Suspense>
          }
        />
        <Route path={routes.households.list} element={<Households />} />
        <Route path={routes.households.new} element={<HouseholdCreate />} />
        <Route path={routes.households.edit.pattern} element={<HouseholdEdit />} />
        <Route path={routes.tags.list} element={<Tags />} />
        <Route path={routes.tags.new} element={<TagCreate />} />
        <Route path={routes.tags.edit.pattern} element={<TagEdit />} />
        <Route element={<RequireAdmin />}>
          <Route path={routes.admin.users.list} element={<Users />} />
          <Route path={routes.admin.users.new} element={<UserCreate />} />
          <Route path={routes.admin.users.edit.pattern} element={<UserEdit />} />
          <Route path={routes.admin.households.list} element={<AdminHouseholds />} />
          <Route path={routes.admin.households.new} element={<AdminHouseholdCreate />} />
          <Route path={routes.admin.households.edit.pattern} element={<AdminHouseholdEdit />} />
          <Route path={routes.admin.serverSettings} element={<ServerSettings />} />
        </Route>
      </Route>
    </Routes>
  )
}
