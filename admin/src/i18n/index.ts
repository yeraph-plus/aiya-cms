import { createI18n } from 'vue-i18n';
import enUS from './locales/en-US';
import zhCN from './locales/zh-CN';

export const APP_LOCALES = ['zh-CN', 'en-US'] as const;
export type AppLocale = (typeof APP_LOCALES)[number];
export const LOCALE_STORAGE_KEY = 'aiya-cms.locale';

export const messages = {
    'zh-CN': zhCN,
    'en-US': enUS
} as const;

function supportedLocale(value: string | null | undefined): AppLocale | null {
    if (!value) return null;
    const normalized = value.trim().toLowerCase();
    if (normalized === 'zh-cn' || normalized.startsWith('zh')) return 'zh-CN';
    if (normalized === 'en-us' || normalized.startsWith('en')) return 'en-US';
    return null;
}

export function resolveInitialLocale(savedLocale: string | null, browserLocales: readonly string[] = []): AppLocale {
    const saved = supportedLocale(savedLocale);
    if (saved) return saved;
    for (const locale of browserLocales) {
        const supported = supportedLocale(locale);
        if (supported) return supported;
    }
    return 'zh-CN';
}

function initialLocale(): AppLocale {
    if (typeof window === 'undefined') return 'zh-CN';
    let saved: string | null = null;
    try {
        saved = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    } catch {
        saved = null;
    }
    return resolveInitialLocale(saved, window.navigator.languages);
}

export const i18n = createI18n({
    legacy: false,
    locale: initialLocale(),
    fallbackLocale: 'zh-CN',
    messages
});

export function setLocale(locale: AppLocale): void {
    i18n.global.locale.value = locale;
    if (typeof document !== 'undefined') document.documentElement.lang = locale;
    if (typeof window !== 'undefined') {
        try {
            window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
        } catch {
            // Locale persistence is optional; rendering continues with the selected locale.
        }
    }
}

export function translate(key: string, params?: Record<string, string | number>): string {
    return params ? i18n.global.t(key, params) : i18n.global.t(key);
}

if (typeof document !== 'undefined') document.documentElement.lang = i18n.global.locale.value;
