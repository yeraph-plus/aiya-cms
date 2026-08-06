<script setup lang="ts">
import {
  DoorArrowRight20Regular as LogoutIcon,
  Settings20Regular as SettingsIcon,
} from '@vicons/fluent'
import { storeToRefs } from 'pinia'

const { renderIcon } = useRender()
const accountStore = useAccountStore()
const { user } = storeToRefs(accountStore)
const { t } = useI18n()
const router = useRouter()
const items = [
  {
    icon: renderIcon(SettingsIcon),
    label: t('userMenu.profile'),
    key: 'profile',
  },
  {
    icon: renderIcon(LogoutIcon),
    label: t('userMenu.logout'),
    key: 'logout',
  },
]

async function handleSelect(key: string) {
  if (key === 'logout') {
    try {
      await accountStore.logout()
    } finally {
      await router.push('/account/login')
    }
    return
  }
  await router.push('/account/profile')
}
</script>

<template>
  <div class="flex items-center" v-bind="$attrs">
    <n-dropdown :options="items" @select="handleSelect">
      <NImage
        class="avatar"
        preview-disabled
        :src="user?.avatar_url ?? '/assets/images/avatar.png'"
        alt="avatar"
        fallbackSrc="/assets/images/avatar.png"
      />
    </n-dropdown>
  </div>
</template>

<style lang="scss">
.username {
  font-size: 0.8rem;
  font-weight: bold;
}

.avatar {
  width: 33px;
  height: 33px;
  border-radius: 50%;
}

.role {
  font-size: 0.7rem;
}

.p-tieredmenu .p-menuitem-active>.p-submenu-list {
  right: 100%;
  left: auto;
}

.rtl {

  .p-tieredmenu .p-menuitem-active>.p-submenu-list {
    right: auto;
    left: 100%;
  }
}
</style>
