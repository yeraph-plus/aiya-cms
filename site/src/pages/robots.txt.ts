import type { APIRoute } from 'astro';

import { loadServerConfig } from '@/lib/config/server';

export const GET: APIRoute = () => {
    const config = loadServerConfig();
    const body =
        config.environment === 'production'
            ? `User-agent: *\nAllow: /\nSitemap: ${new URL('/sitemap.xml', config.siteOrigin).href}\n`
            : 'User-agent: *\nDisallow: /\n';
    return new Response(body, {
        headers: {
            'Content-Type': 'text/plain; charset=utf-8',
            'Cache-Control': config.environment === 'production' ? 'public, max-age=300' : 'no-store'
        }
    });
};
