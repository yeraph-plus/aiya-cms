import { describe, expect, it } from 'vitest';

import { parseTheme } from '@/lib/theme';

describe('theme preference', () => {
    it('accepts only supported theme values', () => {
        expect(parseTheme('system')).toBe('system');
        expect(parseTheme('light')).toBe('light');
        expect(parseTheme('dark')).toBe('dark');
        expect(parseTheme('unexpected')).toBe('system');
        expect(parseTheme(undefined)).toBe('system');
    });
});
