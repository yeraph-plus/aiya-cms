<route lang="yaml">
meta:
  title: tasks
  authRequired: true
  requiredCapability: task:manage
</route>
<script setup lang="ts">
import { adminApi, type TaskInstance } from '~/common/api/admin-api'
const router = useRouter(); const state = ref(''); const page = ref(1); const items = ref<TaskInstance[]>([]); const total = ref(0); const loading = ref(false); const error = ref('')
async function load() { loading.value = true; try { const result = await adminApi.tasks({ state: state.value, page: page.value, size: 20 }); items.value = result.items; total.value = result.total; router.replace({ query: { state: state.value || undefined, page: page.value === 1 ? undefined : page.value } }) } catch (err) { error.value = err instanceof Error ? err.message : '加载失败' } finally { loading.value = false } }
onMounted(load); watch([state, page], load)
</script>
<template><n-card :bordered="false" class="rounded-lg"><div class="mb-4 flex gap-3"><n-select v-model:value="state" clearable placeholder="状态" :options="['pending', 'running', 'succeeded', 'failed', 'cancelled'].map((value) => ({ label: value, value }))" class="w-40" /><n-button @click="load">刷新</n-button></div><n-alert v-if="error" type="error">{{ error }}</n-alert><n-spin :show="loading"><n-empty v-if="!loading && !items.length" description="暂无任务实例" /><n-table v-else striped :single-line="false"><thead><tr><th>类型</th><th>状态</th><th>创建时间</th><th /></tr></thead><tbody><tr v-for="item in items" :key="item.id"><td>{{ item.task_type }}</td><td>{{ item.state }}</td><td>{{ item.created_at }}</td><td><n-button text @click="router.push(`/tasks/${item.id}`)">详情</n-button></td></tr></tbody></n-table><div class="mt-4 flex justify-end"><n-pagination v-model:page="page" :page-size="20" :item-count="total" /></div></n-spin></n-card></template>
