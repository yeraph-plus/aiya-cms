<route lang="yaml">
meta:
  title: comments
  authRequired: true
  requiredCapability: comment:moderate
</route>
<script setup lang="ts">
import { adminApi, type Comment } from '~/common/api/admin-api'
const route = useRoute(); const router = useRouter(); const item = ref<Comment | null>(null); const error = ref('')
onMounted(async () => { try { item.value = await adminApi.comment(String(route.params.id)) } catch (err) { error.value = err instanceof Error ? err.message : 'Load failed' } })
async function moderate(action: string) { if (!item.value) return; try { item.value = await adminApi.moderateComment(item.value.id, action) } catch (err) { error.value = err instanceof Error ? err.message : 'Action failed' } }
</script>
<template><n-button class="mb-4" @click="router.back()">Back</n-button><n-alert v-if="error" type="error">{{ error }}</n-alert><n-card v-if="item" :bordered="false" class="rounded-lg"><div><strong>Content</strong><p>{{ item.content }}</p></div><div><strong>Status</strong><p>{{ item.status }}</p></div><div><strong>Author</strong><p>{{ item.owner_id }}</p></div><div><strong>Target</strong><p>{{ item.target_type }} / {{ item.target_id }}</p></div><div><strong>Created</strong><p>{{ item.created_at }}</p></div><div class="mt-4"><n-button @click="moderate('approve')">Approve</n-button><n-button class="ml-2" @click="moderate('reject')">Reject</n-button><n-button class="ml-2" type="warning" @click="moderate('spam')">Spam</n-button></div></n-card></template>
