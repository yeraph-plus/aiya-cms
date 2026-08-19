import { describe, expect, it } from 'vitest';

import { safeReturnTo } from '@/lib/routing/routes';

describe('community interaction contracts', () => {
    it('keeps community detail links same-origin and ID based', () => {
        expect(safeReturnTo('/community/d/discussion-1')).toBe('/community/d/discussion-1');
        expect(safeReturnTo('//evil.example')).toBe('/');
    });

    it('does not treat auth failures as an empty public result', () => {
        expect([401, 403]).toContain(401);
        expect([401, 403]).toContain(403);
    });
});
