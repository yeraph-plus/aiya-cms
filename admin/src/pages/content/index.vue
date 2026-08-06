<route lang="yaml">
meta:
  title: content
  authRequired: true
  requiredCapabilities:
    - content:create
    - content:update_any
</route>
<script setup lang="ts">
import { adminApi, type ContentItem, type ContentType } from '~/common/api/admin-api'

const router = useRouter()
const types = ref<ContentType[]>([])
const type = ref('post')
const items = ref<ContentItem[]>([])
const total = ref(0)
const q = ref('')
const status = ref('')
const page = ref(1)
const loading = ref(false)
const error = ref('')
const typeOptions = computed(() => types.value.map((item: ContentType) => ({ label: item.type_name, value: item.type_name })))
const statusOptions = computed(() => {
  const metadata = types.value.find((item: ContentType) => item.type_name === type.value)
  const statuses = metadata?.statuses.map((item: Record<string, unknown>) => String(item.slug)) ?? []
  return [...statuses, 'trash'].map((value) => ({ label: value, value }))
})

async function loadTypes() {
  try {
    types.value = await adminApi.contentTypes()
    if (types.value.length && !types.value.some((item: ContentType) => item.type_name === type.value)) type.value = types.value[0].type_name
    if (status.value && !statusOptions.value.some((item: { value: string }) => item.value === status.value)) status.value = ''
  } catch (err) { error.value = err instanceof Error ? err.message : '加载内容类型失败' }
}
async function load() {
  loading.value = true
  try {
    const result = await adminApi.contents(type.value, { q: q.value, status: status.value, page: page.value, size: 20, sort: 'updated_at', order: 'desc' })
    items.value = result.items
    total.value = result.total
    router.replace({ query: { type: type.value, q: q.value || undefined, status: status.value || undefined, page: page.value === 1 ? undefined : page.value } })
  } catch (err) { error.value = err instanceof Error ? err.message : '加载失败' }
  finally { loading.value = false }
}
function open(item: ContentItem) { router.push(`/content/${item.type}/${item.slug}`) }
watch([type, status, page], load)
onMounted(async () => { await loadTypes(); await load() })
</script>
<template>
  <n-card :bordered="false" class="rounded-lg">
    <div class="mb-4 flex flex-wrap gap-3">
      <n-select v-model:value="type" :options="typeOptions" class="w-36" />
      <n-input v-model:value="q" clearable placeholder="搜索标题或 slug" class="max-w-sm" @keyup.enter="page = 1; load()" />
      <n-select v-model:value="status" clearable placeholder="状态" :options="statusOptions" class="w-36" />
      <n-button type="primary" @click="router.push(`/content/${type}/new`)">新建</n-button>
    </div>
    <n-alert v-if="error" type="error" class="mb-4">{{ error }}</n-alert>
    <n-spin :show="loading">
      <n-empty v-if="!loading && !items.length" description="暂无内容" />
      <n-table v-else striped :single-line="false">
        <thead><tr><th>标题</th><th>状态</th><th>评分</th><th>更新时间</th><th /></tr></thead>
        <tbody><tr v-for="item in items" :key="item.id"><td>{{ item.title }} <small class="text-slate-400">/{{ item.slug }}</small></td><td>{{ item.status }}</td><td>{{ item.like_count }} likes / {{ item.rating_count }} ratings</td><td>{{ item.updated_at }}</td><td><n-button text type="primary" @click="open(item)">编辑</n-button></td></tr></tbody>
      </n-table>
      <div class="mt-4 flex justify-end"><n-pagination v-model:page="page" :page-size="20" :item-count="total" /></div>
    </n-spin>
  </n-card>
</template>
