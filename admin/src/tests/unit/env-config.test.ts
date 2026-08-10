import { describe, expect, it } from 'vitest';
import { DEFAULT_ISSUER, resolveOidcIssuer } from '@/env';

describe('admin environment configuration', () => {
    it('uses the single AIYA_ISSUER value exposed by Vite', () => {
        expect(resolveOidcIssuer({ AIYA_ISSUER: 'https://api.example/' })).toBe('https://api.example');
    });

    it('defaults to the compose backend port', () => {
        expect(resolveOidcIssuer({})).toBe('http://127.0.0.1:8000');
        expect(DEFAULT_ISSUER).toBe('http://127.0.0.1:8000');
    });
});
