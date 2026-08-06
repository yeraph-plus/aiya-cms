import type { LocationQueryRaw } from 'vue-router'

type QueryValue = string | number | boolean | undefined
export type QueryState = Record<string, QueryValue>

function readValue(value: string | string[] | null | undefined): string | undefined {
  if (Array.isArray(value)) return value[0]
  return value ?? undefined
}

/** Keep list filters shareable without duplicating URL parsing in each page. */
export function useQueryState<T extends QueryState>(defaults: T) {
  const route = useRoute()
  const router = useRouter()
  const state = reactive({ ...defaults }) as T

  function read(): T {
    for (const key of Object.keys(defaults) as Array<keyof T>) {
      const value = readValue(route.query[String(key)])
      if (value === undefined) continue
      const defaultValue = defaults[key]
      state[key] = (
        typeof defaultValue === 'number' ? Number(value) : value
      ) as T[typeof key]
    }
    return state
  }

  async function write(overrides: Partial<T> = {}): Promise<void> {
    Object.assign(state, overrides)
    const query: LocationQueryRaw = {}
    for (const [key, value] of Object.entries(state)) {
      if (value !== undefined && value !== '') query[key] = String(value)
    }
    await router.replace({ query })
  }

  onMounted(read)
  return { state, read, write }
}
