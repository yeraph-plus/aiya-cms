export const SUPPORTED_LANGUAGES = ['zh', 'en'] as const
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number]

export const PRIMARY_COLORS = [
  '#009b43',
  '#DB0B51',
  '#0099e0',
  '#ff7300',
  '#008f85',
  '#9575cd',
  '#FFCC00',
] as const
export type PresetColor = (typeof PRIMARY_COLORS)[number]
export const DEFAULT_PRIMARY_COLOR: PresetColor = PRIMARY_COLORS[0]

type LayoutPreferences = Record<string, unknown>

function isRecord(value: unknown): value is LayoutPreferences {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function normalizeLanguage(value: unknown): SupportedLanguage {
  return value === 'en' ? 'en' : 'zh'
}

export function localeForLanguage(language: SupportedLanguage): 'zh-CN' | 'en' {
  return language === 'zh' ? 'zh-CN' : 'en'
}

export function normalizeThemeColor(value: unknown): PresetColor {
  if (
    typeof value === 'string' &&
    PRIMARY_COLORS.includes(value as PresetColor)
  ) {
    return value as PresetColor
  }
  return DEFAULT_PRIMARY_COLOR
}

export function normalizeLayoutPreferences(value: unknown): LayoutPreferences {
  const preferences = isRecord(value) ? { ...value } : {}
  const normalized: LayoutPreferences = {
    ...preferences,
    activeLanguage: normalizeLanguage(preferences.activeLanguage),
    themeColor: normalizeThemeColor(preferences.themeColor),
  }
  delete normalized.flatDesign
  return normalized
}

export function readAndMigrateLayoutPreferences(
  storage: Storage = window.localStorage,
): LayoutPreferences {
  const raw = storage.getItem('layout')
  if (!raw) return normalizeLayoutPreferences({})

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    parsed = {}
  }

  const normalized = normalizeLayoutPreferences(parsed)
  const serialized = JSON.stringify(normalized)
  if (serialized !== raw) storage.setItem('layout', serialized)
  return normalized
}
