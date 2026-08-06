<route lang="yaml">
meta:
  title: dashboard
  authRequired: true
</route>
<script setup lang="ts">
import { health, type HealthResponse } from '~/common/api/api-client'
import { adminApi } from '~/common/api/admin-api'

const { t } = useI18n()
const healthState = ref<HealthResponse | null>(null)
const healthError = ref(false)
const dashboardError = ref('')
const isCheckingHealth = ref(true)
const summary = ref<Awaited<ReturnType<typeof adminApi.dashboard>> | null>(null)
const stats = computed(() => [
  { key: 'contents_total', label: t('menu.content'), value: summary.value?.contents_total },
  { key: 'comments_pending', label: t('menu.comments'), value: summary.value?.comments_pending },
  { key: 'users_total', label: t('menu.users'), value: summary.value?.users_total },
  { key: 'tasks_active', label: t('menu.tasks'), value: summary.value?.tasks_active },
].filter((item) => item.value !== null && item.value !== undefined))

onMounted(async () => {
  const [healthResult, dashboardResult] = await Promise.allSettled([
    health(),
    adminApi.dashboard(),
  ])
  if (healthResult.status === 'fulfilled') {
    healthState.value = healthResult.value
  } else {
    healthError.value = true
  }
  if (dashboardResult.status === 'fulfilled') {
    summary.value = dashboardResult.value
  } else {
    dashboardError.value =
      dashboardResult.reason instanceof Error
        ? dashboardResult.reason.message
        : 'Dashboard statistics are unavailable'
  }
  isCheckingHealth.value = false
})
</script>

<template>
  <div>
    <n-alert v-if="dashboardError" type="warning" class="mb-4">
      {{ dashboardError }}
    </n-alert>
    <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      <n-card v-for="s in stats" :key="s.key" :bordered="false" class="rounded-lg">
        <div class="flex items-center justify-between">
          <span class="text-slate-400">{{ s.label }}</span>
          <span class="text-xl font-semibold">{{ s.value }}</span>
        </div>
      </n-card>
    </div>
    <n-card :bordered="false" class="mt-6 rounded-lg" :title="t('health.title')">
      <n-skeleton v-if="isCheckingHealth" text :repeat="2" />
      <n-alert v-else-if="healthError" type="error" :title="t('health.unavailable')">
        {{ t('health.retryHint') }}
      </n-alert>
      <template v-else-if="healthState">
        <n-alert :type="healthState.status === 'ok' ? 'success' : 'warning'" :title="healthState.status">
          {{ healthState.environment }} · {{ healthState.version }}
        </n-alert>
        <n-descriptions class="mt-4" bordered :column="2" size="small">
          <n-descriptions-item v-for="(status, dependency) in healthState.dependencies" :key="dependency" :label="dependency">
            {{ status }}
          </n-descriptions-item>
        </n-descriptions>
      </template>
    </n-card>
  </div>
</template>
