import { describe, expect, it } from 'vitest';

import { isSafeUrl, markdownToText, renderMarkdown, sanitizeUrl } from '@/lib/markdown';

describe('secure markdown renderer', () => {
    it('escapes raw HTML and does not create iframe or script elements', () => {
        const html = renderMarkdown('<script>alert(1)</script>\n\n<iframe src="https://evil.example"></iframe>');

        expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
        expect(html).toContain('&lt;iframe');
        expect(html).not.toMatch(/<\/?(?:script|iframe)\b/iu);
    });

    it('keeps safe links and drops dangerous destinations', () => {
        const html = renderMarkdown('[safe](/docs) [external](https://example.com) [bad](java&#x73;cript:alert(1))');

        expect(html).toContain('<a href="/docs">safe</a>');
        expect(html).toContain('<a href="https://example.com">external</a>');
        expect(html).not.toContain('javascript:');
        expect(html).not.toContain('<a href="java');
    });

    it('escapes code blocks and exposes readable text for SEO descriptions', () => {
        const html = renderMarkdown('```html\n<div class="x">& unsafe</div>\n```');

        expect(html).toContain('&lt;div class=&quot;x&quot;&gt;&amp; unsafe&lt;/div&gt;');
        expect(markdownToText('## A title\n\nA **short** summary.')).toBe('A title A short summary.');
    });

    it('accepts only non-dangerous URL schemes', () => {
        expect(isSafeUrl('https://example.com')).toBe(true);
        expect(isSafeUrl('#section')).toBe(true);
        expect(sanitizeUrl('javascript:alert(1)')).toBeNull();
        expect(sanitizeUrl('data:text/html,<svg onload=alert(1)>')).toBeNull();
        expect(sanitizeUrl('//evil.example/path')).toBeNull();
    });
});
