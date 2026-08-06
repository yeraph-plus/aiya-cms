import {
  DataTrending16Regular as AuditIcon,
  ChatMultiple20Regular as CommentsIcon,
  BoxMultiple20Regular as ContentIcon,
  Board24Regular as DashboardIcon,
  Settings28Regular as SettingsIcon,
  CheckmarkCircle24Regular as TasksIcon,
  Folder24Regular as TaxonomyIcon,
  People24Regular as UsersIcon,
} from '@vicons/fluent'
import type { SidebarMenuOption } from '~/components/shared/SidebarMenu.vue'

type Translator = (key: string) => string

export type SidebarCapabilities = ReadonlySet<string>

type NavigationEntry = SidebarMenuOption & {
  requiredCapabilities?: readonly string[]
}

/** aiya-cms 管理员端导航：概览 + 7 个功能分区（M2 起逐个填充）。 */
export function buildSidebarMenu(
  t: Translator,
  capabilities?: SidebarCapabilities,
): SidebarMenuOption[] {
  const entries: NavigationEntry[] = [
    {
      label: t('menu.dashboard'),
      key: 'index',
      route: '/',
      icon: DashboardIcon,
    },
    {
      label: t('menu.users'),
      key: 'users',
      route: '/users',
      icon: UsersIcon,
      requiredCapabilities: ['user:read_any'],
    },
    {
      label: t('menu.content'),
      key: 'content',
      route: '/content',
      icon: ContentIcon,
      requiredCapabilities: ['content:create', 'content:update_any'],
    },
    {
      label: t('menu.taxonomy'),
      key: 'taxonomy',
      route: '/taxonomy',
      icon: TaxonomyIcon,
      requiredCapabilities: ['term:assign', 'term:manage'],
    },
    {
      label: t('menu.comments'),
      key: 'comments',
      route: '/comments',
      icon: CommentsIcon,
      requiredCapabilities: ['comment:moderate'],
    },
    {
      label: t('menu.audit'),
      key: 'audit',
      route: '/audit',
      icon: AuditIcon,
      requiredCapabilities: ['audit:read'],
    },
    {
      label: t('menu.settings'),
      key: 'settings',
      route: '/settings',
      icon: SettingsIcon,
      requiredCapabilities: ['setting:read'],
    },
    {
      label: t('menu.tasks'),
      key: 'tasks',
      route: '/tasks',
      icon: TasksIcon,
      requiredCapabilities: ['task:manage'],
    },
  ]

  if (!capabilities) return entries
  return entries.filter(
    (entry) =>
      !entry.requiredCapabilities ||
      entry.requiredCapabilities.some((capability) =>
        capabilities.has(capability),
      ),
  )
}
