import { acceptHMRUpdate, defineStore } from 'pinia'
import {
  ApiError,
  clearAccessToken,
  getAccessToken,
} from '~/common/api/api-client'
import type {
  Account,
  LoginViewModel,
  RegisterViewModel,
} from '~/models/Account'
import AccountService from '~/services/account.service'

export const useAccountStore = defineStore('account', () => {
  const user = ref<Account | null>(null)
  const isLoading = ref(false)
  const loginFailed = ref(false)

  async function login(loginInfo: LoginViewModel): Promise<boolean> {
    isLoading.value = true
    try {
      const response = await AccountService.login(loginInfo)
      const profile = await AccountService.me()
      user.value = {
        token: response.access_token,
        username: profile.username,
        capabilities: [...profile.capabilities],
      }
      loginFailed.value = false
      return true
    } catch {
      loginFailed.value = true
      return false
    } finally {
      isLoading.value = false
    }
  }

  async function logout() {
    try {
      await AccountService.logout()
    } finally {
      clearAccessToken()
      user.value = null
    }
  }

  async function register(registerInfo: RegisterViewModel) {
    isLoading.value = true
    try {
      const response = await AccountService.register(registerInfo)
      const pair = await AccountService.login({
        username: registerInfo.username,
        password: registerInfo.password,
      })
      const profile = await AccountService.me()
      user.value = {
        token: pair.access_token,
        username: profile.username || response.username,
        capabilities: [...profile.capabilities],
      }
      return true
    } catch {
      return false
    } finally {
      isLoading.value = false
    }
  }

  async function restoreSession(): Promise<boolean> {
    try {
      const pair = await AccountService.refresh()
      const profile = await AccountService.me()
      user.value = {
        token: pair.access_token,
        username: profile.username,
        capabilities: [...profile.capabilities],
      }
      return true
    } catch (error) {
      if (error instanceof ApiError && error.status !== 401) throw error
      user.value = null
      return false
    }
  }

  function isAuthenticated() {
    return getAccessToken() !== null
  }

  function hasCapability(capability: string) {
    return user.value?.capabilities?.includes(capability) ?? false
  }

  function hasAnyCapability(capabilities: readonly string[]) {
    return capabilities.some((capability) => hasCapability(capability))
  }

  return {
    user,
    isLoading,
    loginFailed,
    login,
    logout,
    isAuthenticated,
    register,
    restoreSession,
    hasCapability,
    hasAnyCapability,
  }
})

if (import.meta.hot)
  import.meta.hot.accept(acceptHMRUpdate(useAccountStore, import.meta.hot))
