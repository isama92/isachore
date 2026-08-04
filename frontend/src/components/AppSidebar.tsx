import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router'
import {
  CalendarOff,
  ChartColumn,
  ChevronRight,
  CircleUser,
  ClipboardList,
  History,
  Home,
  House,
  LogOut,
  Settings,
  Shield,
  Tag as TagIcon,
  Users,
} from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { hasRoleSomewhere } from '../lib/permissions'
import { routes } from '../lib/routes'
import { fullName, initials } from '../lib/user'
import BrandMark from './brand/BrandMark'
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
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from '@/components/ui/sidebar'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'

export default function AppSidebar() {
  const { user, memberships, logout } = useAuth()
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const { setOpenMobile } = useSidebar()
  if (!user) return null

  // Close the mobile drawer after a navigation; harmless on desktop.
  const closeMobile = () => setOpenMobile(false)

  // Statistics needs a deputy somewhere; the two management pages need an organiser. History
  // used to share the Statistics expression and no longer does: it is unconditional now,
  // because the endpoint narrows per household (everybody's closures where you are a deputy,
  // your own where you are a helper) rather than refusing.
  const canSeeStatistics = hasRoleSomewhere(memberships, 'deputy')
  const canManage = hasRoleSomewhere(memberships, 'organiser')

  // Household roles decide which of these a user sees at all: a page they cannot use is
  // hidden rather than shown and then refused. `show` is per item because the roles are per
  // household while this nav is global, so the rule is "reaches the role somewhere" - see
  // hasRoleSomewhere. The five unconditional items are open to every role (completing chores
  // is what a helper is for, History shows them their own closures, and the household pages
  // are read-only unless you own one). Whoever adds an item here must add the matching
  // RequireRole route in App.tsx: hiding a link is not a permission check, and neither is the
  // guard - the API is.
  const items = [
    { to: routes.home, icon: Home, label: t('sidebar.home') },
    { to: routes.unscheduled, icon: CalendarOff, label: t('sidebar.unscheduled') },
    { to: routes.history, icon: History, label: t('sidebar.history') },
    {
      to: routes.statistics,
      icon: ChartColumn,
      label: t('sidebar.statistics'),
      show: canSeeStatistics,
    },
    { to: routes.tags.list, icon: TagIcon, label: t('sidebar.tags'), show: canManage },
    { to: routes.chores.list, icon: ClipboardList, label: t('sidebar.chores'), show: canManage },
    { to: routes.households.list, icon: House, label: t('sidebar.households') },
    { to: routes.profile, icon: CircleUser, label: t('sidebar.profile') },
  ].filter((item) => item.show !== false)

  // Admin section: a foldable parent (links nowhere) with one sub-item per
  // admin page. Add future admin pages here.
  const adminItems = [
    { to: routes.admin.users.list, icon: Users, label: t('sidebar.users') },
    { to: routes.admin.households.list, icon: House, label: t('sidebar.adminHouseholds') },
    { to: routes.admin.serverSettings, icon: Settings, label: t('sidebar.serverSettings') },
  ]
  const adminActive = pathname.startsWith('/admin')

  // Home is exact; other sections also match their nested routes (e.g.
  // /chores/new keeps "Chores" active).
  const isActive = (to: string) =>
    to === '/' ? pathname === '/' : pathname === to || pathname.startsWith(`${to}/`)

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="gap-2">
        {/* The wordmark is display:none in icon mode, which also takes it out of the
            accessibility tree, so the link carries its own name. "isachore" is
            deliberately untranslated, like everywhere else it appears. */}
        <Link
          to={routes.home}
          onClick={closeMobile}
          aria-label="isachore"
          className="flex items-center gap-2 px-1 py-1 outline-hidden focus-visible:ring-2 focus-visible:ring-sidebar-ring rounded-md"
        >
          <BrandMark />
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
              {user.is_admin && (
                <Collapsible asChild defaultOpen={adminActive} className="group/collapsible">
                  <SidebarMenuItem>
                    <CollapsibleTrigger asChild>
                      <SidebarMenuButton tooltip={t('sidebar.admin')} isActive={adminActive}>
                        <Shield />
                        <span>{t('sidebar.admin')}</span>
                        <ChevronRight className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90" />
                      </SidebarMenuButton>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <SidebarMenuSub>
                        {adminItems.map((sub) => (
                          <SidebarMenuSubItem key={sub.to}>
                            <SidebarMenuSubButton asChild isActive={isActive(sub.to)}>
                              <Link to={sub.to} onClick={closeMobile}>
                                <sub.icon />
                                <span>{sub.label}</span>
                              </Link>
                            </SidebarMenuSubButton>
                          </SidebarMenuSubItem>
                        ))}
                      </SidebarMenuSub>
                    </CollapsibleContent>
                  </SidebarMenuItem>
                </Collapsible>
              )}
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
