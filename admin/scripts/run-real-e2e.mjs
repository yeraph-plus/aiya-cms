import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const cli = resolve(root, 'node_modules/@playwright/test/cli.js')
const result = spawnSync(process.execPath, [cli, 'test', 'e2e/real-auth.spec.ts'], {
  cwd: root,
  env: { ...process.env, AIYA_E2E_REAL: 'true' },
  stdio: 'inherit',
})
process.exit(result.status ?? 1)
