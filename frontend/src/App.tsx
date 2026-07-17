import { Route, Routes } from 'react-router'
import RequireAdmin from './components/RequireAdmin'
import RequireAuth from './components/RequireAuth'
import ServerSettings from './pages/admin/ServerSettings'
import Users from './pages/admin/Users'
import ChoreCreate from './pages/ChoreCreate'
import Chores from './pages/Chores'
import ConfirmAccount from './pages/ConfirmAccount'
import Home from './pages/Home'
import Login from './pages/Login'
import Profile from './pages/Profile'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/confirm" element={<ConfirmAccount />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Home />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/chores" element={<Chores />} />
        <Route path="/chores/new" element={<ChoreCreate />} />
        <Route element={<RequireAdmin />}>
          <Route path="/admin/users" element={<Users />} />
          <Route path="/admin/server-settings" element={<ServerSettings />} />
        </Route>
      </Route>
    </Routes>
  )
}
