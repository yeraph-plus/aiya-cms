import { describe, expect, it } from 'vitest';

import {
    contentCollectionPath,
    contentDetailPath,
    describePublicContent,
    normalizePublicContent,
    publicContentMetadata
} from '@/lib/seo/content';

describe('public content fallback', () => {
    it('keeps route semantics distinct from generic API type names', () => {
        expect(contentCollectionPath('post')).toBe('/posts');
        expect(contentCollectionPath('page')).toBe('/pages');
        expect(contentCollectionPath('work')).toBe('/works');
        expect(contentDetailPath('work', 'a work')).toBe('/works/a%20work');
    });

    it('normalizes only public content kinds and derives readable metadata', () => {
        const content = normalizePublicContent(
            {
                id: '1',
                type_name: 'work',
                slug: 'sample',
                title: 'Sample work',
                body: '# Body',
                excerpt: null,
                body_format: 'markdown',
                status: 'published',
                updated_at: '2026-01-01T00:00:00Z',
                data: {
                    creator: 'A creator',
                    tags: ['one', 'two'],
                    provider_locator: 'must not render',
                    secret: 'must not render'
                }
            },
            'work'
        );

        expect(content?.indexable).toBe(true);
        expect(describePublicContent(content!)).toBe('Body');
        expect(publicContentMetadata(content!, 'zh-CN')).toEqual([
            { label: '创作者', value: 'A creator' },
            { label: '标签', value: 'one · two' }
        ]);
        const page = normalizePublicContent(
            {
                id: '2',
                type_name: 'page',
                slug: 'docs',
                title: 'Docs',
                status: 'published',
                data: { category: 'Guide', tags: ['must not render'] }
            },
            'page'
        );
        expect(publicContentMetadata(page!, 'en')).toEqual([{ label: 'Category', value: 'Guide' }]);
        expect(normalizePublicContent({ type_name: 'unknown', id: '1', slug: 'x', title: 'x' })).toBeNull();
    });
});
