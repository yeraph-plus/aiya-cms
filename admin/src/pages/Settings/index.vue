<route lang="yaml">
meta:
  title: settings
  authRequired: true
  requiredCapability: setting:read
</route>

<script setup lang="ts">
import { adminApi, type SettingGroup } from '~/common/api/admin-api'

const account = useAccountStore()
const groups = ref<SettingGroup[]>([])
const loading = ref(false)
const saving = ref<string | null>(null)
const error = ref('')
const notice = ref('')
const canUpdate = computed(() => account.hasCapability('setting:update'))

type SettingField = SettingGroup['fields'][number]

function updateField(field: SettingField, value: unknown) {
  field.value = value
}

function displayType(field: SettingField) {
  return field.type === 'boolean' || field.type === 'integer' || field.type === 'number' || field.type === 'string'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    groups.value = await adminApi.settings()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载设置失败'
  } finally {
    loading.value = false
  }
}

async function save(group: SettingGroup) {
  if (!canUpdate.value) return
  saving.value = group.slug
  error.value = ''
  notice.value = ''
  try {
    const values = Object.fromEntries(group.fields.map((field) => [field.slug, field.value]))
    const updated = await adminApi.updateSettingGroup(group.slug, { values, unset: [] })
    const index = groups.value.findIndex((item: SettingGroup) => item.slug === group.slug)
    if (index >= 0) groups.value[index] = updated
    notice.value = '设置已保存'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存设置失败'
  } finally {
    saving.value = null
  }
}

function reset() {
  void load()
}

onMounted(load)
</script>

<template>
  <n-spin :show="loading">
    <n-alert v-if="error" type="error" class="mb-4">{{ error }}</n-alert>
    <n-alert v-if="notice" type="success" class="mb-4">{{ notice }}</n-alert>
    <n-empty v-if="!loading && !groups.length" description="暂无设置" />
    <div v-else class="grid gap-4">
      <n-card v-for="group in groups" :key="group.slug" :bordered="false" class="rounded-lg">
        <template #header>{{ group.title }}</template>
        <p v-if="group.description" class="mb-4 text-slate-500">{{ group.description }}</p>
        <n-form label-placement="top" class="grid gap-4 md:grid-cols-2">
          <n-form-item v-for="field in group.fields" :key="field.slug" :label="field.title">
            <template #feedback>{{ field.description }}</template>
            <n-switch
              v-if="field.type === 'boolean'"
              :value="Boolean(field.value)"
              :disabled="!canUpdate"
              @update:value="(value: boolean) => updateField(field, value)"
            />
            <n-input-number
              v-else-if="field.type === 'integer' || field.type === 'number'"
              :value="typeof field.value === 'number' ? field.value : undefined"
              :disabled="!canUpdate"
              class="w-full"
              @update:value="(value: number | null) => updateField(field, value)"
            />
            <n-input
              v-else-if="displayType(field)"
              :value="field.value == null ? '' : String(field.value)"
              :disabled="!canUpdate"
              @update:value="(value: string) => updateField(field, value)"
            />
            <n-input
              v-else
              type="textarea"
              :value="JSON.stringify(field.value ?? null, null, 2)"
              :disabled="!canUpdate"
              @update:value="(value: string) => updateField(field, value)"
            />
          </n-form-item>
        </n-form>
        <div class="mt-4 flex gap-3">
          <n-button v-if="canUpdate" type="primary" :loading="saving === group.slug" @click="save(group)">保存</n-button>
          <n-button secondary @click="reset">重置</n-button>
        </div>
      </n-card>
    </div>
  </n-spin>
</template>
