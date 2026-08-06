<route lang="yaml">
meta:
  title: content
  authRequired: true
  requiredCapabilities:
    - content:create
    - content:update_any
</route>
<script setup lang="ts">
import { adminApi, type ContentType } from '~/common/api/admin-api'

const route = useRoute()
const router = useRouter()
const type = String(route.params.type)
const metadata = ref<ContentType | null>(null)
const title = ref('')
const slug = ref('')
const content = ref('')
const dataText = ref('{}')
const preview = ref(false)
const saving = ref(false)
const error = ref('')

const fieldSummary = computed(() =>
  metadata.value?.fields.map((field: Record<string, unknown>) => String(field.title ?? field.slug)).join(', ') || 'none',
)
const taxonomySummary = computed(() =>
  metadata.value?.taxonomy_groups.map((group: Record<string, unknown>) => String(group.title ?? group.slug)).join(', ') || 'none',
)

async function save() {
  saving.value = true
  try {
    await adminApi.createContent(type, {
      title: title.value,
      slug: slug.value,
      content: content.value,
      data: JSON.parse(dataText.value),
    })
    router.push(`/content/${type}/${slug.value}`)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Save failed'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    metadata.value = (await adminApi.contentTypes()).find((item) => item.type_name === type) ?? null
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Loading failed'
  }
})
</script>
<template>
  <n-card :bordered="false" class="rounded-lg">
    <template #header>New {{ type }}</template>
    <n-alert v-if="error" type="error" class="mb-4">{{ error }}</n-alert>
    <n-form label-placement="top">
      <n-form-item label="Title"><n-input v-model:value="title" /></n-form-item>
      <n-form-item label="Slug"><n-input v-model:value="slug" /></n-form-item>
      <n-form-item label="Content">
        <div class="w-full">
          <n-button size="small" @click="preview = !preview">{{ preview ? 'Edit' : 'Preview' }}</n-button>
          <n-input v-if="!preview" v-model:value="content" type="textarea" :rows="14" class="mt-2" />
          <div v-else class="prose mt-2 min-h-60 whitespace-pre-wrap rounded border p-3">{{ content }}</div>
        </div>
      </n-form-item>
      <n-form-item label="Extension data (JSON)"><n-input v-model:value="dataText" type="textarea" :rows="6" /></n-form-item>
      <n-button type="primary" :loading="saving" @click="save">Save</n-button>
      <n-button class="ml-3" @click="router.back()">Cancel</n-button>
    </n-form>
    <n-alert v-if="metadata" type="info" class="mt-4">
      Fields: {{ fieldSummary }}; taxonomy groups: {{ taxonomySummary }}
    </n-alert>
  </n-card>
</template>
