export type User = {
  id: number
  email: string
  name: string
  is_admin: boolean
  is_active: boolean
  created_at: string
}

export type Me = User & { impersonating: boolean }
