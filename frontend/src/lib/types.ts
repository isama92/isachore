export type User = {
  id: number
  email: string
  name: string
  is_admin: boolean
  is_active: boolean
  created_at: string
  avatar_url: string | null
}

export type Me = User & { impersonating: boolean }

export type RepeatPeriod = 'manual' | 'hourly' | 'daily' | 'weekly' | 'monthly' | 'yearly'

export type AssignmentType = 'manual' | 'alphabetical' | 'random' | 'least_done'

export type Tag = {
  id: number
  name: string
  color: string
}

export type Chore = {
  id: number
  title: string
  description: string | null
  start_date: string
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  created_at: string
  assignees: User[]
  tags: Tag[]
}

// The households endpoint only returns what the assignee picker needs.
export type HouseholdMember = Pick<User, 'id' | 'name'>

export type Household = {
  id: number
  name: string
  created_at: string
  members: HouseholdMember[]
}
