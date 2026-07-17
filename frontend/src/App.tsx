import { Route, Routes } from 'react-router'
import RequireAdmin from './components/RequireAdmin'
import RequireAuth from './components/RequireAuth'
import AdminHouseholdCreate from './pages/admin/HouseholdCreate'
import AdminHouseholdEdit from './pages/admin/HouseholdEdit'
import AdminHouseholds from './pages/admin/Households'
import ServerSettings from './pages/admin/ServerSettings'
import Users from './pages/admin/Users'
import AcceptInvite from './pages/AcceptInvite'
import ChoreCreate from './pages/ChoreCreate'
import Chores from './pages/Chores'
import ConfirmAccount from './pages/ConfirmAccount'
import Home from './pages/Home'
import HouseholdCreate from './pages/HouseholdCreate'
import HouseholdEdit from './pages/HouseholdEdit'
import Households from './pages/Households'
import Login from './pages/Login'
import Profile from './pages/Profile'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/confirm" element={<ConfirmAccount />} />
      <Route path="/invite" element={<AcceptInvite />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Home />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/chores" element={<Chores />} />
        <Route path="/chores/new" element={<ChoreCreate />} />
        <Route path="/households" element={<Households />} />
        <Route path="/households/new" element={<HouseholdCreate />} />
        <Route path="/households/:id/edit" element={<HouseholdEdit />} />
        <Route element={<RequireAdmin />}>
          <Route path="/admin/users" element={<Users />} />
          <Route path="/admin/households" element={<AdminHouseholds />} />
          <Route path="/admin/households/new" element={<AdminHouseholdCreate />} />
          <Route path="/admin/households/:id/edit" element={<AdminHouseholdEdit />} />
          <Route path="/admin/server-settings" element={<ServerSettings />} />
        </Route>
      </Route>
    </Routes>
  )
}
