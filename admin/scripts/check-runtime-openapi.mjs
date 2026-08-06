import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const snapshotPath = resolve(import.meta.dirname, '..', '..', 'openapi.json')
const runtimeOrigin = (process.env.AIYA_RUNTIME_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '')

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical)
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonical(item)]),
    )
  }
  return value
}

const snapshot = JSON.parse(await readFile(snapshotPath, 'utf8'))
const response = await fetch(`${runtimeOrigin}/openapi.json`)
if (!response.ok) {
  throw new Error(`Runtime OpenAPI request failed: HTTP ${response.status}`)
}
const runtime = await response.json()
function routeTree(schema) {
  return Object.fromEntries(
    Object.entries(schema.paths)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([path, operations]) => [
        path,
        Object.keys(operations)
          .filter((method) => method !== 'parameters')
          .sort(),
      ]),
  )
}

const expected = JSON.stringify(canonical(routeTree(snapshot)))
const actual = JSON.stringify(canonical(routeTree(runtime)))

if (expected !== actual) {
  const expectedPaths = new Set(Object.keys(snapshot.paths))
  const actualPaths = new Set(Object.keys(runtime.paths))
  const missing = [...expectedPaths].filter((path) => !actualPaths.has(path)).sort()
  const extra = [...actualPaths].filter((path) => !expectedPaths.has(path)).sort()
  throw new Error(
    [
      'Runtime OpenAPI paths differ from the frozen contract.',
      missing.length ? `Missing: ${missing.join(', ')}` : '',
      extra.length ? `Extra: ${extra.join(', ')}` : '',
    ]
      .filter(Boolean)
      .join('\n'),
  )
}

console.log(`Runtime OpenAPI matches frozen contract (${Object.keys(runtime.paths).length} paths).`)
