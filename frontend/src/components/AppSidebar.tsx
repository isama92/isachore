import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router'
import {
  CalendarOff,
  ChartColumn,
  ChevronRight,
  ClipboardList,
  History,
  Home,
  House,
  LogOut,
  ScrollText,
  Settings,
  Shield,
  Tag as TagIcon,
  Users,
} from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { hasRoleSomewhere, ownsAnyHousehold } from '../lib/permissions'
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
  // Logs is gated on OWNERSHIP, which is not a rung on the ladder: an organiser who does not
  // own the household manages its chores but does not get the record of that management.
  const canSeeLogs = ownsAnyHousehold(memberships)

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
    { to: routes.logs, icon: ScrollText, label: t('sidebar.logs'), show: canSeeLogs },
    { to: routes.tags.list, icon: TagIcon, label: t('sidebar.tags'), show: canManage },
    { to: routes.chores.list, icon: ClipboardList, label: t('sidebar.chores'), show: canManage },
    { to: routes.households.list, icon: House, label: t('sidebar.households') },
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
        {/* The way in to Profile, which has no nav item of its own. It has to be the whole
            block rather than a button beside the name, because in icon mode the primitive
            hides a SidebarMenuAction along with the text, and Profile would become
            unreachable while the sidebar is collapsed. The chevron is the resting
            affordance, since hover styling says nothing on a touch screen; it does not
            rotate, unlike the Admin item's, which is the same glyph meaning "expand". */}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              asChild
              // Same string as the link's name. Collapsed, the chevron is hidden and this
              // tooltip is the only thing left saying the avatar goes anywhere.
              tooltip={t('sidebar.profileOf', { name: fullName(user) })}
              isActive={isActive(routes.profile)}
            >
              {/* Labelled rather than named by its contents, which would announce the whole
                  email address on every encounter and leave the destination until last
                  ("Ada Lovelace ada@example.com Profile"). Destination first, identity kept,
                  address dropped - it is on the page this links to. The label also survives
                  icon mode, where the text is display:none and out of the tree entirely,
                  which is the same reason the brand link above carries one. */}
              <Link
                to={routes.profile}
                onClick={closeMobile}
                aria-label={t('sidebar.profileOf', { name: fullName(user) })}
              >
                {/* aria-label replaces the link's NAME, not its contents, so without this the
                    initials stay in the accessibility tree for anyone reading through the
                    link with a virtual cursor. Decorative either way: they render the name
                    that sits right beside them. */}
                <Avatar aria-hidden="true">
                  {user.avatar_url && <AvatarImage src={user.avatar_url} alt="" />}
                  <AvatarFallback className="bg-primary/10 font-bold text-primary">
                    {initials(user)}
                  </AvatarFallback>
                </Avatar>
                {/* Sibling spans, each truncating and carrying its own title, so hovering the
                    clipped email explains the email rather than the name. The email tracks
                    the button's hover/active colour: the row takes the accent background now
                    that it is a link, and a pinned muted foreground measures 2.7:1 against
                    it - permanently so on /profile, where the row stays active. */}
                <div className="grid min-w-0 flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
                  <span
                    className="truncate text-sm font-bold text-sidebar-foreground"
                    title={fullName(user)}
                  >
                    {fullName(user)}
                  </span>
                  <span
                    className="truncate text-xs font-medium text-muted-foreground group-hover/menu-button:text-sidebar-accent-foreground group-data-active/menu-button:text-sidebar-accent-foreground"
                    title={user.email}
                  >
                    {user.email}
                  </span>
                </div>
                <ChevronRight className="text-muted-foreground group-hover/menu-button:text-sidebar-accent-foreground group-data-active/menu-button:text-sidebar-accent-foreground group-data-[collapsible=icon]:hidden" />
              </Link>
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
