export const locales = ['zh-CN', 'en'] as const;
export type Locale = (typeof locales)[number];
export const LOCALE_COOKIE = 'aiya-locale';

const zhCN = {
    'site.name': 'Aiya CMS',
    'site.tagline': '开放、清晰、由内容驱动的数字空间',
    'nav.home': '首页',
    'nav.account': '用户中心',
    'nav.community': '社区',
    'nav.communityTags': '社区标签',
    'nav.login': '登录',
    'nav.logout': '退出登录',
    'nav.skip': '跳到主要内容',
    'language.label': '语言',
    'language.zh-CN': '简体中文',
    'language.en': 'English',
    'theme.label': '外观',
    'theme.system': '跟随系统',
    'theme.light': '浅色',
    'theme.dark': '深色',
    'controls.open': '打开显示设置',
    'home.eyebrow': '用户站基础框架',
    'home.title': '内容、社区与个人空间的统一入口',
    'home.description':
        '当前已完成服务端渲染、路由控制、OIDC 会话、多语言和主题基础设施。业务内容将在对应 FastAPI 合同完成后接入。',
    'home.status.ssr': 'Astro SSR',
    'home.status.auth': 'OIDC BFF',
    'home.status.api': 'OpenAPI 类型',
    'home.status.a11y': '可访问控件',
    'home.foundation.kicker': '基础架构 01',
    'home.foundation.title': 'HTML 优先，按需交互。',
    'community.eyebrow': '社区',
    'community.title': '社区讨论',
    'community.description': '浏览公开讨论、回复和社区标签。',
    'community.navigation': '社区导航',
    'community.tags': '社区标签',
    'community.tagsDescription': '按标签浏览公开讨论。',
    'community.discussions': '讨论',
    'community.replies': '回复',
    'community.posts': '帖子',
    'community.discussion': '讨论',
    'community.taggedDiscussions': '该标签下的公开讨论。',
    'community.empty': '暂无公开讨论。',
    'community.unavailable': '社区暂时不可用，请稍后重试。',
    'account.title': '用户中心',
    'account.description': '此页面由服务端路由守卫保护，不向浏览器暴露 access token、refresh token 或 client secret。',
    'account.signedInAs': '当前登录身份',
    'account.placeholder': '用户资料、积分与会员业务模块将在 user_center API 完成后装配。',
    'auth.loggedOut.title': '已安全退出',
    'auth.loggedOut.description': '本地用户站会话已销毁，OIDC Provider 会话也已完成退出处理。',
    'auth.error.title': '无法完成登录',
    'auth.error.description': '登录事务无效、已过期或身份服务暂时不可用。请重新发起登录。',
    'error.notFound.title': '页面不存在',
    'error.notFound.description': '请求的页面不存在，或尚未在当前产品 manifest 中启用。',
    'error.unavailable.title': '服务暂时不可用',
    'error.unavailable.description': '认证会话存储暂时不可用，受保护页面已按安全策略关闭。'
} as const;

export type MessageKey = keyof typeof zhCN;

const en = {
    'site.name': 'Aiya CMS',
    'site.tagline': 'An open, legible, content-led digital space',
    'nav.home': 'Home',
    'nav.account': 'Account',
    'nav.community': 'Community',
    'nav.communityTags': 'Community tags',
    'nav.login': 'Sign in',
    'nav.logout': 'Sign out',
    'nav.skip': 'Skip to main content',
    'language.label': 'Language',
    'language.zh-CN': '简体中文',
    'language.en': 'English',
    'theme.label': 'Appearance',
    'theme.system': 'System',
    'theme.light': 'Light',
    'theme.dark': 'Dark',
    'controls.open': 'Open display settings',
    'home.eyebrow': 'User-site foundation',
    'home.title': 'One entry point for content, community, and account spaces',
    'home.description':
        'Server rendering, route controls, OIDC sessions, localization, and theming are ready. Business content will connect after its FastAPI contracts land.',
    'home.status.ssr': 'Astro SSR',
    'home.status.auth': 'OIDC BFF',
    'home.status.api': 'OpenAPI types',
    'home.status.a11y': 'Accessible controls',
    'home.foundation.kicker': 'Foundation 01',
    'home.foundation.title': 'HTML first. Interaction by intent.',
    'community.eyebrow': 'Community',
    'community.title': 'Community discussions',
    'community.description': 'Browse public discussions, replies, and community tags.',
    'community.navigation': 'Community navigation',
    'community.tags': 'Community tags',
    'community.tagsDescription': 'Browse public discussions by tag.',
    'community.discussions': 'discussions',
    'community.replies': 'replies',
    'community.posts': 'posts',
    'community.discussion': 'Discussion',
    'community.taggedDiscussions': 'Public discussions in this tag.',
    'community.empty': 'No public discussions yet.',
    'community.unavailable': 'The community is temporarily unavailable. Try again later.',
    'account.title': 'Account',
    'account.description':
        'This page is protected by a server-side route guard. Access tokens, refresh tokens, and the client secret never reach the browser.',
    'account.signedInAs': 'Signed in as',
    'account.placeholder':
        'Profile, points, and membership modules will be composed after the user_center API is available.',
    'auth.loggedOut.title': 'Signed out safely',
    'auth.loggedOut.description': 'The local site session was destroyed and the OpenID Provider logout flow completed.',
    'auth.error.title': 'Sign-in could not be completed',
    'auth.error.description':
        'The sign-in transaction is invalid, expired, or the identity service is unavailable. Start a new sign-in.',
    'error.notFound.title': 'Page not found',
    'error.notFound.description':
        'The requested page does not exist or is not enabled by the current product manifest.',
    'error.unavailable.title': 'Service unavailable',
    'error.unavailable.description':
        'The authentication session store is unavailable, so protected routes are closed safely.'
} satisfies Record<MessageKey, string>;

const catalogs: Record<Locale, Record<MessageKey, string>> = {
    'zh-CN': zhCN,
    en
};

export function isLocale(value: string): value is Locale {
    return locales.includes(value as Locale);
}

export function localeFromPath(pathname: string): Locale {
    return pathname === '/en' || pathname.startsWith('/en/') ? 'en' : 'zh-CN';
}

export function t(locale: Locale, key: MessageKey): string {
    return catalogs[locale][key];
}
