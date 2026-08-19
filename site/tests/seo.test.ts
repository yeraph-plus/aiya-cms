import { describe, expect, it } from 'vitest';

import { buildContentJsonLd, buildSeoMetadata, serializeJsonLd } from '@/lib/seo';

describe('public SEO primitives', () => {
    it('builds an absolute query-free canonical and configurable robots value', () => {
        const metadata = buildSeoMetadata({
            title: 'Public post',
            description: 'A readable description',
            siteName: 'Aiya CMS',
            siteOrigin: 'https://site.example',
            canonical: '/posts/hello?sort=latest',
            noindex: true,
            nofollow: false,
            ogType: 'article'
        });

        expect(metadata.title).toBe('Public post · Aiya CMS');
        expect(metadata.canonical).toBe('https://site.example/posts/hello');
        expect(metadata.robots).toBe('noindex, follow');
        expect(metadata.openGraph.type).toBe('article');
        expect(metadata.openGraph.url).toBe(metadata.canonical);
    });

    it('serializes JSON-LD so user content cannot close its script element', () => {
        const jsonLd = buildContentJsonLd({
            kind: 'post',
            title: '</script><script>alert(1)</script>',
            description: 'Description',
            canonical: 'https://site.example/posts/safe'
        });
        const serialized = serializeJsonLd(jsonLd);

        expect(serialized).not.toContain('</script>');
        expect(serialized).toContain('\\u003c/script\\u003e');
        expect(jsonLd['@type']).toBe('Article');
    });
});
