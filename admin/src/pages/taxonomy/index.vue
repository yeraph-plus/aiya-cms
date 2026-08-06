<route lang="yaml">
meta:
  title: taxonomy
  authRequired: true
  requiredCapabilities:
    - term:assign
    - term:manage
</route>
<script setup lang="ts">
import { adminApi, type Term } from '~/common/api/admin-api'
const router = useRouter()
const contentType = ref('post')
const group = ref('')
const terms = ref<Term[]>([])
const loading = ref(false)
const error = ref('')
async function load() { loading.value = true; try { terms.value = (await adminApi.terms(contentType.value, { group: group.value })).items } catch (err) { error.value = err instanceof Error ? err.message : '加载失败' } finally { loading.value = false } }
async function remove(term: Term) { if (!window.confirm(`确认删除 ${term.name}？`)) return; try { await adminApi.deleteTerm(term.content_type, term.id); await load() } catch (err) { error.value = err instanceof Error ? err.message : '删除失败' } }
onMounted(load)
watch([contentType, group], load)
</script>
<template><n-card :bordered="false" class="rounded-lg"><div class="mb-4 flex flex-wrap gap-3"><n-input v-model:value="contentType" placeholder="内容类型" class="w-36" /><n-input v-model:value="group" clearable placeholder="分组" class="w-36" /><n-button type="primary" @click="router.push(`/taxonomy/${contentType}/new`)">新建分类</n-button></div><n-alert v-if="error" type="error" class="mb-4">{{ error }}</n-alert><n-spin :show="loading"><n-empty v-if="!loading && !terms.length" description="暂无分类" /><n-table v-else striped :single-line="false"><thead><tr><th>名称</th><th>Slug</th><th>内容类型</th><th>分组</th><th /></tr></thead><tbody><tr v-for="term in terms" :key="term.id"><td>{{ term.name }}</td><td>{{ term.slug }}</td><td>{{ term.content_type }}</td><td>{{ term.group }}</td><td><n-button text type="primary" @click="router.push(`/taxonomy/${term.content_type}/${term.id}`)">编辑</n-button><n-button text type="error" class="ml-2" @click="remove(term)">删除</n-button></td></tr></tbody></n-table></n-spin></n-card></template>
