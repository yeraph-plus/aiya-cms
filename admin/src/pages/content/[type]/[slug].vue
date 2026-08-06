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

const route = useRoute()
const router = useRouter()
const type = String(route.params.type)
const slugParam = String(route.params.slug)
const item = ref<ContentItem | null>(null)
const metadata = ref<ContentType | null>(null)
const title = ref('')
const slug = ref('')
const content = ref('')
const dataText = ref('{}')
const status = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')

const availableActions = computed(() => {
  const actions = (metadata.value?.transitions ?? [])
    .filter((transition: Record<string, unknown>) => {
      const fromStatuses = transition.from_statuses
      return Array.isArray(fromStatuses) && fromStatuses.includes(status.value)
    })
    .map((transition: Record<string, unknown>) => String(transition.action))
  if (status.value === 'trash') actions.push('restore')
  else actions.push('trash')
  return [...new Set(actions)]
})

async function load() {
  try {
    const [result, types] = await Promise.all([
      adminApi.content(type, slugParam),
      adminApi.contentTypes(),
    ])
    item.value = result.content
    metadata.value = types.find((entry) => entry.type_name === type) ?? null
    title.value = result.content.title
    slug.value = result.content.slug
    content.value = result.content.content
    dataText.value = JSON.stringify(result.content.data, null, 2)
    status.value = result.content.status
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Loading failed'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!item.value) return
  saving.value = true
  try {
    item.value = await adminApi.updateContent(type, item.value.id, {
      title: title.value,
      slug: slug.value,
      content: content.value,
      data: JSON.parse(dataText.value),
    })
    status.value = item.value.status
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Save failed'
  } finally {
    saving.value = false
  }
}

async function runAction(name: string) {
  if (!item.value || !window.confirm(`Confirm action: ${name}`)) return
  try {
    item.value = await adminApi.contentAction(type, item.value.id, name)
    status.value = item.value.status
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Action failed'
  }
}

onMounted(load)
</script>
<template>
  <n-spin :show="loading">
    <n-button class="mb-4" @click="router.back()">Back</n-button>
    <n-alert v-if="error" type="error" class="mb-4">{{ error }}
    </n-alert>
    <n-card v-if="item" :bordered="false" class="rounded-lg">
      <template #header>{{ title }} <n-tag size="small">{{ status }}
      </n-tag></template>
      <n-form label-placement="top">
        <n-form-item label="Title"><n-input v-model:value="title" /></n-form-item>
        <n-form-item label="Slug"><n-input v-model:value="slug" /></n-form-item>
        <n-form-item label="Content"><n-input v-model:value="content" type="textarea" :rows="14" /></n-form-item>
        <n-form-item label="Extension data (JSON)"><n-input v-model:value="dataText" type="textarea" :rows="8" /></n-form-item>
        <n-button type="primary" :loading="saving" @click="save">Save</n-button>
        <n-button
          v-for="action in availableActions"
          :key="action"
          class="ml-3"
          :type="action === 'trash' ? 'warning' : 'default'"
          @click="runAction(action)"
        >
          {{ action }}
        </n-button>
      </n-form>
    </n-card>
  </n-spin>
</template>
