import * as api from '~/common/api/api-client'
import type { LoginViewModel, RegisterViewModel } from '~/models/Account'

class AccountService {
  async login(loginInfo: LoginViewModel): Promise<api.TokenPair> {
    return api.login(loginInfo.username, loginInfo.password)
  }

  async register(registerModel: RegisterViewModel): Promise<api.UserRead> {
    return api.register(
      registerModel.username,
      registerModel.email,
      registerModel.password,
      registerModel.displayName,
    )
  }

  async me(): Promise<api.AuthMe> {
    return api.me()
  }

  async refresh(): Promise<api.TokenPair> {
    return api.refresh()
  }

  async logout(): Promise<void> {
    return api.logout()
  }
}

export default new AccountService()
