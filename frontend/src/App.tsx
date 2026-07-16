import { Route, Routes } from 'react-router'
import RequireAdmin from './components/RequireAdmin'
import RequireAuth from './components/RequireAuth'
import Users from './pages/admin/Users'
import ChoreCreate from './pages/ChoreCreate'
import Chores from './pages/Chores'
import Home from './pages/Home'
import Login from './pages/Login'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Home />} />
        <Route path="/chores" element={<Chores />} />
        <Route path="/chores/new" element={<ChoreCreate />} />
        <Route element={<RequireAdmin />}>
          <Route path="/admin/users" element={<Users />} />
        </Route>
      </Route>
    </Routes>
  )
}
