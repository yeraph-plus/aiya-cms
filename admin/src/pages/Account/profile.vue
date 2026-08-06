<script setup lang="ts">
import { me, type AuthMe } from '~/common/api/api-client'
const profile = ref<AuthMe | null>(null)
const loading = ref(true)
const error = ref('')
onMounted(async () => { try { profile.value = await me() } catch (err) { error.value = err instanceof Error ? err.message : 'Load failed' } finally { loading.value = false } })
</script>
<route lang="yaml">
meta:
  title: profile
  authRequired: true
  breadcrumb:
    - accountSettings
</route>
<template>
  <n-spin :show="loading">
    <n-alert v-if="error" type="error">{{ error }}</n-alert>
    <n-card v-if="profile" :bordered="false" class="rounded-lg">
      <template #header>Account overview</template>
      <div class="grid gap-3 md:grid-cols-2">
        <div><strong>Username</strong><p>{{ profile.username }}</p></div>
        <div><strong>Display name</strong><p>{{ profile.display_name }}</p></div>
        <div><strong>Email</strong><p>{{ profile.email }}</p></div>
        <div><strong>Status</strong><p>{{ profile.status }}</p></div>
        <div><strong>Roles</strong><p>{{ profile.roles.join(', ') || '-' }}</p></div>
        <div><strong>Capabilities</strong><p>{{ profile.capabilities.join(', ') || '-' }}</p></div>
      </div>
      <n-alert class="mt-4" type="info">Read-only account overview.</n-alert>
    </n-card>
  </n-spin>
</template>
