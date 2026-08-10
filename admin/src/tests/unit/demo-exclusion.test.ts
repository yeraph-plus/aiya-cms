import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const srcRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const demoRoot = resolve(srcRoot, 'demo');

function readSource(rel: string): string {
    return readFileSync(resolve(srcRoot, rel), 'utf8');
}

function listProductionSources(): string[] {
    const result: string[] = [];
    const walk = (dir: string) => {
        for (const entry of readdirSync(dir)) {
            const full = resolve(dir, entry);
            if (full.startsWith(demoRoot)) continue;
            if (statSync(full).isDirectory()) {
                walk(full);
            } else if (full.endsWith('.vue') || full.endsWith('.ts')) {
                result.push(full);
            }
        }
    };
    walk(srcRoot);
    return result;
}

describe('demo production exclusion', () => {
    it('production route files contain no demo reference', () => {
        for (const rel of ['router/public-routes.ts', 'router/app-routes.ts']) {
            const source = readSource(rel);
            expect(source, `${rel} must not reference demo`).not.toMatch(/demo/i);
        }
    });

    it('production menu contains no demo entry', () => {
        const source = readSource('navigation/menu.ts');
        expect(source).not.toMatch(/demo/i);
    });

    it('demo is only imported from the dev-guarded router entry', () => {
        for (const full of listProductionSources()) {
            const source = readFileSync(full, 'utf8');
            if (full.endsWith(`${sep}router${sep}index.ts`)) {
                expect(source, 'router/index.ts must guard demo routes behind DEV').toMatch(/import\.meta\.env\.DEV/);
                continue;
            }
            expect(source, `${full} imports demo`).not.toMatch(/@\/demo/);
        }
    });

    it('router registers demo routes only behind the DEV guard', () => {
        const source = readSource('router/index.ts');
        expect(source).toMatch(/import\s*\{[^}]*demoRoutes[^}]*\}\s*from\s*'@\/demo\/routes'/);
        expect(source).toMatch(/if\s*\(\s*import\.meta\.env\.DEV\s*\)\s*\{[^}]*routes\.push\(\.\.\.demoRoutes\)/);
    });
});
