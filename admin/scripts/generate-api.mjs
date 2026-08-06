import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const cli = resolve(root, 'node_modules/openapi-typescript/bin/cli.js')
const input = resolve(root, '..', 'openapi.json')
const output = resolve(root, 'src/common/api/generated/api.ts')
const result = spawnSync(process.execPath, [cli, input, '-o', output], {
  cwd: root,
  stdio: 'inherit',
})
process.exit(result.status ?? 1)
