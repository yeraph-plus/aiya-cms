import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const cli = resolve(root, 'node_modules/openapi-typescript/bin/cli.js')
const input = resolve(root, '..', 'openapi.json')
const generated = resolve(root, 'src/common/api/generated/api.ts')
const tempDir = mkdtempSync(join(tmpdir(), 'aiya-openapi-'))
const candidate = join(tempDir, 'api.ts')

try {
  const result = spawnSync(process.execPath, [cli, input, '-o', candidate], {
    cwd: root,
    stdio: 'inherit',
  })
  if (result.status !== 0) process.exit(result.status ?? 1)

  const expected = readFileSync(generated, 'utf8')
  const actual = readFileSync(candidate, 'utf8')
  if (expected !== actual) {
    console.error('Generated OpenAPI client is stale. Run npm run generate:api.')
    process.exit(1)
  }
  console.log('Generated OpenAPI client is up to date.')
} finally {
  rmSync(tempDir, { recursive: true, force: true })
}
