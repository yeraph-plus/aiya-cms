<route lang="yaml">
meta:
  title: audit
  authRequired: true
  requiredCapability: audit:read
</route>
<script setup lang="ts">
import { adminApi, type AuditLog } from '~/common/api/admin-api'
const router = useRouter(); const action = ref(''); const page = ref(1); const items = ref<AuditLog[]>([]); const total = ref(0); const error = ref(''); const loading = ref(false)
async function load() { loading.value = true; try { const result = await adminApi.audit({ action: action.value, page: page.value, size: 20 }); items.value = result.items; total.value = result.total; router.replace({ query: { action: action.value || undefined, page: page.value === 1 ? undefined : page.value } }) } catch (err) { error.value = err instanceof Error ? err.message : '加载失败' } finally { loading.value = false } }
onMounted(load); watch([action, page], load)
</script>
<template><n-card :bordered="false" class="rounded-lg"><div class="mb-4 flex gap-3"><n-input v-model:value="action" clearable placeholder="按 action 筛选" @keyup.enter="page = 1; load()" /><n-button @click="load">刷新</n-button></div><n-alert v-if="error" type="error">{{ error }}</n-alert><n-spin :show="loading"><n-empty v-if="!loading && !items.length" description="暂无审计日志" /><n-table v-else striped :single-line="false"><thead><tr><th>Action</th><th>Actor</th><th>Target</th><th>时间</th><th /></tr></thead><tbody><tr v-for="item in items" :key="item.id"><td>{{ item.action }}</td><td>{{ item.actor_id ?? item.actor_type }}</td><td>{{ item.target_type }} / {{ item.target_id }}</td><td>{{ item.created_at }}</td><td><n-button text @click="router.push(`/audit/${item.id}`)">详情</n-button></td></tr></tbody></n-table><div class="mt-4 flex justify-end"><n-pagination v-model:page="page" :page-size="20" :item-count="total" /></div></n-spin></n-card></template>
