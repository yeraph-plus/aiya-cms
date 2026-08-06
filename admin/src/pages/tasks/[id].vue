<route lang="yaml">
meta:
  title: tasks
  authRequired: true
  requiredCapability: task:manage
</route>
<script setup lang="ts">
import { adminApi, type TaskInstance } from '~/common/api/admin-api'
const route = useRoute(); const router = useRouter(); const item = ref<TaskInstance | null>(null); const error = ref('')
onMounted(async () => { try { item.value = await adminApi.task(String(route.params.id)) } catch (err) { error.value = err instanceof Error ? err.message : 'Load failed' } })
</script>
<template><n-button class="mb-4" @click="router.back()">Back</n-button><n-alert v-if="error" type="error">{{ error }}</n-alert><n-card v-if="item" :bordered="false"><div><strong>Type</strong><p>{{ item.task_type }}</p></div><div><strong>State</strong><p>{{ item.state }}</p></div><div><strong>Payload</strong><pre>{{ JSON.stringify(item.payload, null, 2) }}</pre></div><div><strong>Result</strong><pre>{{ JSON.stringify(item.result, null, 2) }}</pre></div><div><strong>Created</strong><p>{{ item.created_at }}</p></div></n-card></template>
