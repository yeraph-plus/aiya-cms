import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const adminRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const repoRoot = resolve(adminRoot, '..');
const openapiPath = join(repoRoot, 'openapi.json');
const schemaPath = join(adminRoot, 'src/api/schema.d.ts');

function sha256(filePath: string): string {
    return createHash('sha256').update(readFileSync(filePath)).digest('hex');
}

describe('generated type no-drift gate', () => {
    it('openapi.json matches the committed openapi.sha256', () => {
        const expected = readFileSync(join(repoRoot, 'openapi.sha256'), 'utf8').split(/\s+/)[0];
        expect(sha256(openapiPath)).toBe(expected);
    });

    it('schema.d.ts is byte-identical to a fresh openapi-typescript run', () => {
        const tmp = mkdtempSync(join(adminRoot, 'node_modules/.tmp/schema-drift-'));
        try {
            const out = join(tmp, 'schema.d.ts');
            execFileSync(process.execPath, [resolve(adminRoot, 'node_modules/openapi-typescript/bin/cli.js'), openapiPath, '-o', out], { cwd: adminRoot, stdio: 'pipe' });
            expect(readFileSync(schemaPath, 'utf8'), 'src/api/schema.d.ts drifted; run npm run generate:api').toBe(readFileSync(out, 'utf8'));
        } finally {
            rmSync(tmp, { recursive: true, force: true });
        }
    });
});
