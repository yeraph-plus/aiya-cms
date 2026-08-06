import messages from '@intlify/unplugin-vue-i18n/messages'
import { createI18n } from 'vue-i18n'
import {
  localeForLanguage,
  normalizeLanguage,
  readAndMigrateLayoutPreferences,
} from '~/common/preferences/layout-preferences'
import type { AppModule } from '~/types'

const storedValue = readAndMigrateLayoutPreferences()
const locale = localeForLanguage(normalizeLanguage(storedValue.activeLanguage))

const i18n = createI18n({
  legacy: false,
  locale,
  fallbackLocale: 'zh',
  messages,
})

export const install: AppModule = (app) => {
  app.use(i18n)
}

export default i18n
