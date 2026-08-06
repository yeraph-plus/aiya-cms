<route lang="yaml">
meta:
  title: audit
  authRequired: true
  requiredCapability: audit:read
</route>
<script setup lang="ts">
import { adminApi, type AuditLog } from '~/common/api/admin-api'
const route = useRoute(); const router = useRouter(); const item = ref<AuditLog | null>(null); const error = ref('')
onMounted(async () => { try { item.value = await adminApi.auditLog(String(route.params.id)) } catch (err) { error.value = err instanceof Error ? err.message : 'Load failed' } })
</script>
<template><n-button class="mb-4" @click="router.back()">Back</n-button><n-alert v-if="error" type="error">{{ error }}</n-alert><n-card v-if="item" :bordered="false"><div><strong>Action</strong><p>{{ item.action }}</p></div><div><strong>Actor</strong><p>{{ item.actor_id ?? item.actor_type }}</p></div><div><strong>Target</strong><p>{{ item.target_type }} / {{ item.target_id }}</p></div><div><strong>Context</strong><pre>{{ JSON.stringify(item.context, null, 2) }}</pre></div><div><strong>Created</strong><p>{{ item.created_at }}</p></div></n-card></template>
