import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router'
import { CircleUser, ClipboardList, Home, LogOut, Shield } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { fullName, initials } from '../lib/user'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'

export default function AppSidebar() {
  const { user, logout } = useAuth()
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const { setOpenMobile } = useSidebar()
  if (!user) return null

  // Close the mobile drawer after a navigation; harmless on desktop.
  const closeMobile = () => setOpenMobile(false)

  const items = [
    { to: '/', icon: Home, label: t('sidebar.home') },
    { to: '/chores', icon: ClipboardList, label: t('sidebar.chores') },
    { to: '/profile', icon: CircleUser, label: t('sidebar.profile') },
    ...(user.is_admin ? [{ to: '/admin/users', icon: Shield, label: t('sidebar.admin') }] : []),
  ]

  // Home is exact; other sections also match their nested routes (e.g.
  // /chores/new keeps "Chores Management" active).
  const isActive = (to: string) =>
    to === '/' ? pathname === '/' : pathname === to || pathname.startsWith(`${to}/`)

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="gap-2">
        <Link
          to="/"
          onClick={closeMobile}
          className="flex items-center gap-2 px-1 py-1 outline-hidden focus-visible:ring-2 focus-visible:ring-sidebar-ring rounded-md"
        >
          <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary text-sm font-extrabold text-primary-foreground shadow-logo">
            ✓
          </span>
          <span className="font-display text-lg font-extrabold tracking-tight group-data-[collapsible=icon]:hidden">
            isachore
          </span>
        </Link>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              asChild
              tooltip={fullName(user)}
              className="cursor-default hover:bg-transparent active:bg-transparent"
            >
              <div>
                <Avatar>
                  {user.avatar_url && <AvatarImage src={user.avatar_url} alt={fullName(user)} />}
                  <AvatarFallback className="bg-primary/10 font-bold text-primary">
                    {initials(user)}
                  </AvatarFallback>
                </Avatar>
                <div className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
                  <span className="truncate text-sm font-bold text-sidebar-foreground">
                    {fullName(user)}
                  </span>
                  <span className="truncate text-xs font-medium text-muted-foreground">
                    {user.email}
                  </span>
                </div>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <nav aria-label={t('sidebar.nav')}>
          <SidebarGroup>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton asChild isActive={isActive(item.to)} tooltip={item.label}>
                    <Link to={item.to} onClick={closeMobile}>
                      <item.icon />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
        </nav>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              tooltip={t('sidebar.logout')}
              className="text-destructive hover:bg-destructive/10 hover:text-destructive active:bg-destructive/10 active:text-destructive"
              onClick={() => {
                closeMobile()
                void logout()
              }}
            >
              <LogOut />
              <span>{t('sidebar.logout')}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
