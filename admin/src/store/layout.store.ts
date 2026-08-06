import { acceptHMRUpdate, defineStore } from 'pinia'
import {
  DEFAULT_PRIMARY_COLOR,
  localeForLanguage,
  normalizeLanguage,
  normalizeThemeColor,
  type SupportedLanguage,
} from '~/common/preferences/layout-preferences'

export const useLayoutStore = defineStore(
  'layout',
  () => {
    const { t, locale } = useI18n()
    const collapsed = ref(false)
    const forceCollapsed = ref(false)
    const mobileMenuClosed = ref(true)
    const mobileMode = ref(false)
    const activeLanguage = ref<SupportedLanguage>('zh')
    const isRtl = ref(false)
    const themeColor = ref(DEFAULT_PRIMARY_COLOR)
    const isDark = ref(false)
    const isWelcomeShown = ref(false)
    const isFluid = ref(false)
    const supportEnabled = ref(false)

    const dialogPlacement = computed(() => (isRtl.value ? 'left' : 'right'))

    watch(
      () => useWindowSize().width.value,
      (newValue: number) => {
        forceCollapsed.value = newValue <= 1024
        mobileMode.value = newValue < 600
      },
      { immediate: true },
    )

    function toggleSidebar() {
      if (mobileMode.value) mobileMenuClosed.value = false
      else collapsed.value = !collapsed.value

      window.umami?.track('ToggleSidebar')
    }

    function closeSidebar() {
      mobileMenuClosed.value = true
    }

    function setDarkTheme(state: boolean) {
      isDark.value = state
    }

    function toggleTheme() {
      isDark.value = !isDark.value
      window.umami?.track('ToggleDarkMode', {
        theme: isDark.value ? 'Dark' : 'Light',
      })
    }

    function changeLanguage(lang: string) {
      const language = normalizeLanguage(lang)
      activeLanguage.value = language
      locale.value = localeForLanguage(language)
      window.umami?.track('LanguageChange', { language })
      showWelcome()
    }

    function setThemeColor(color: string) {
      const normalizedColor = normalizeThemeColor(color)
      themeColor.value = normalizedColor
      window.umami?.track('ChangeTheme', { color: normalizedColor })
    }

    function showWelcome() {
      useNotifyStore().clear()
      setTimeout(() => {
        useNotifyStore().notify({
          body: t('notify.welcome'),
          type: 'success',
          duration: 10000,
        })
        isWelcomeShown.value = true
      }, 1500)
    }

    function resetWelcomeState() {
      isWelcomeShown.value = false
    }

    function $reset() {
      mobileMode.value = false
    }

    function setSupportEnabled() {
      supportEnabled.value = true
    }

    return {
      collapsed,
      forceCollapsed,
      mobileMode,
      toggleSidebar,
      toggleTheme,
      isRtl,
      activeLanguage,
      changeLanguage,
      isDark,
      setThemeColor,
      themeColor,
      dialogPlacement,
      isWelcomeShown,
      showWelcome,
      resetWelcomeState,
      closeSidebar,
      $reset,
      mobileMenuClosed,
      isFluid,
      setDarkTheme,
      supportEnabled,
      setSupportEnabled,
    }
  },
  {
    persist: {
      omit: ['mobileMode', 'forceCollapsed', 'supportEnabled'],
    },
  },
)

if (import.meta.hot)
  import.meta.hot.accept(acceptHMRUpdate(useLayoutStore, import.meta.hot))
