<route lang="yaml">
meta:
  title: comments
  authRequired: true
  requiredCapability: comment:moderate
</route>
<script setup lang="ts">
import { adminApi, type Comment } from '~/common/api/admin-api'
const router = useRouter(); const status = ref('pending'); const q = ref(''); const page = ref(1); const items = ref<Comment[]>([]); const total = ref(0); const loading = ref(false); const error = ref('')
async function load() { loading.value = true; try { const result = await adminApi.comments({ status: status.value, q: q.value, page: page.value, size: 20 }); items.value = result.items; total.value = result.total; router.replace({ query: { status: status.value, q: q.value || undefined, page: page.value === 1 ? undefined : page.value } }) } catch (err) { error.value = err instanceof Error ? err.message : '加载失败' } finally { loading.value = false } }
async function moderate(comment: Comment, action: string) { try { await adminApi.moderateComment(comment.id, action); await load() } catch (err) { error.value = err instanceof Error ? err.message : '操作失败' } }
async function remove(comment: Comment) { if (!window.confirm('确认删除评论？')) return; try { await adminApi.deleteComment(comment.id); await load() } catch (err) { error.value = err instanceof Error ? err.message : '删除失败' } }
onMounted(load); watch([status, page], load)
</script>
<template><n-card :bordered="false" class="rounded-lg"><div class="mb-4 flex flex-wrap gap-3"><n-select v-model:value="status" :options="['pending', 'approved', 'rejected', 'spam'].map((value) => ({ label: value, value }))" class="w-36" /><n-input v-model:value="q" clearable placeholder="搜索评论" @keyup.enter="page = 1; load()" /><n-button @click="load">刷新</n-button></div><n-alert v-if="error" type="error" class="mb-4">{{ error }}</n-alert><n-spin :show="loading"><n-empty v-if="!loading && !items.length" description="暂无待审评论" /><n-table v-else striped :single-line="false"><thead><tr><th>内容</th><th>目标</th><th>状态</th><th>时间</th><th /></tr></thead><tbody><tr v-for="comment in items" :key="comment.id"><td class="max-w-md truncate">{{ comment.content }}</td><td>{{ comment.target_type }} / {{ comment.target_id }}</td><td>{{ comment.status }}</td><td>{{ comment.created_at }}</td><td><n-button text @click="router.push(`/comments/${comment.id}`)">详情</n-button><n-button v-if="comment.status !== 'approved'" text type="success" class="ml-2" @click="moderate(comment, 'approve')">通过</n-button><n-button v-if="comment.status !== 'spam'" text type="warning" class="ml-2" @click="moderate(comment, 'spam')">垃圾</n-button><n-button text type="error" class="ml-2" @click="remove(comment)">删除</n-button></td></tr></tbody></n-table><div class="mt-4 flex justify-end"><n-pagination v-model:page="page" :page-size="20" :item-count="total" /></div></n-spin></n-card></template>
