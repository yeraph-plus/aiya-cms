import node from '@astrojs/node';
import vue from '@astrojs/vue';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'astro/config';

const siteOrigin = process.env.SITE_ORIGIN ?? 'http://127.0.0.1:4321';
const production = process.env.SITE_ENVIRONMENT === 'production';

export default defineConfig({
    site: siteOrigin,
    output: 'server',
    adapter: node({ mode: 'standalone' }),
    integrations: [vue()],
    i18n: {
        locales: ['zh-CN', 'en'],
        defaultLocale: 'zh-CN',
        routing: {
            prefixDefaultLocale: false
        }
    },
    session: {
        driver: {
            entrypoint: new URL('./src/lib/session/redis-driver.ts', import.meta.url)
        },
        cookie: {
            name: production ? '__Host-aiya-site' : 'aiya-site-dev',
            httpOnly: true,
            sameSite: 'lax',
            secure: production,
            path: '/'
        },
        ttl: 60 * 60 * 24 * 7
    },
    vite: {
        plugins: [tailwindcss()]
    },
    prefetch: {
        prefetchAll: false,
        defaultStrategy: 'hover'
    }
});
