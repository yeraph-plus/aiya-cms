import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const srcRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const adminRoot = resolve(srcRoot, '..');

function readSource(rel: string): string {
    return readFileSync(resolve(srcRoot, rel), 'utf8');
}

function listProductionSources(): string[] {
    const result: string[] = [];
    const walk = (dir: string) => {
        for (const entry of readdirSync(dir)) {
            if (entry === 'tests') continue;
            const full = resolve(dir, entry);
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
    it('does not ship demo source, public assets, or styles', () => {
        for (const rel of ['src/demo', 'public/demo', 'src/assets/demo']) {
            expect(existsSync(resolve(adminRoot, rel)), `${rel} must be removed`).toBe(false);
        }
    });

    it('production menu contains no demo entry', () => {
        const source = readSource('navigation/menu.ts');
        expect(source).not.toMatch(/demo/i);
    });

    it('production sources contain no demo import or route', () => {
        for (const full of listProductionSources()) {
            const source = readFileSync(full, 'utf8');
            expect(source, `${full} references demo`).not.toMatch(/(?:@\/demo|\/demo|assets\/demo)/i);
        }
    });

    it('router does not register demo routes', () => {
        const source = readSource('router/index.ts');
        expect(source).not.toMatch(/demoRoutes|routes\.push/);
    });
});
