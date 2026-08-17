import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const adminRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const repoRoot = resolve(adminRoot, '..');

function read(path: string): string {
    return readFileSync(path, 'utf8');
}

describe('administrator production topology', () => {
    it('builds static assets and serves them from unprivileged nginx', () => {
        const dockerfile = read(resolve(adminRoot, 'Dockerfile'));
        expect(dockerfile).toContain('RUN npm ci');
        expect(dockerfile).toContain('RUN npm run build');
        expect(dockerfile).toContain('nginxinc/nginx-unprivileged:1.31.3-alpine');
        expect(dockerfile).not.toMatch(/vite\s+(?:preview|--host)/);
    });

    it('configures same-origin API/OIDC proxy, SPA fallback, cache and security headers', () => {
        const nginx = read(resolve(adminRoot, 'nginx.conf'));
        expect(nginx).toMatch(/location \/api\//);
        expect(nginx).toMatch(/location \/oidc\//);
        expect(nginx).toContain('/.well-known/openid-configuration');
        expect(nginx).toMatch(/try_files \$uri \$uri\/ \/index\.html/);
        expect(nginx).toMatch(/immutable/);
        expect(nginx).toMatch(/Content-Security-Policy/);
        expect(nginx).toMatch(/X-Content-Type-Options/);
    });

    it('keeps the unfinished user site behind an explicit compose profile', () => {
        const compose = read(resolve(repoRoot, 'compose.yaml'));
        expect(compose).toMatch(/AIYA_APP_PROFILE:\s*\$\{AIYA_APP_PROFILE:-management\}/);
        expect(compose).toMatch(/\n\s{2}admin:\s*\n/);
        expect(compose).toMatch(/profiles:\s*\[site\]/);
    });
});
