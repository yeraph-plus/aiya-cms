<route lang="yaml">
meta:
  title: taxonomy
  authRequired: true
  requiredCapabilities:
    - term:manage
</route>
<script setup lang="ts">
import { adminApi } from '~/common/api/admin-api'
const route = useRoute(); const router = useRouter(); const type = String(route.params.type); const group = ref('category'); const slug = ref(''); const name = ref(''); const dataText = ref('{}'); const saving = ref(false); const error = ref('')
async function save() { saving.value = true; try { await adminApi.createTerm(type, { group: group.value, slug: slug.value, name: name.value, data: JSON.parse(dataText.value) }); router.push('/taxonomy') } catch (err) { error.value = err instanceof Error ? err.message : '保存失败' } finally { saving.value = false } }
</script>
<template><n-card :bordered="false" class="rounded-lg"><template #header>新建分类</template><n-alert v-if="error" type="error">{{ error }}</n-alert><n-form label-placement="top"><n-form-item label="内容类型"><n-input :value="type" disabled /></n-form-item><n-form-item label="分组"><n-input v-model:value="group" /></n-form-item><n-form-item label="Slug"><n-input v-model:value="slug" /></n-form-item><n-form-item label="名称"><n-input v-model:value="name" /></n-form-item><n-form-item label="扩展数据 JSON"><n-input v-model:value="dataText" type="textarea" /></n-form-item><n-button type="primary" :loading="saving" @click="save">保存</n-button><n-button class="ml-3" @click="router.back()">取消</n-button></n-form></n-card></template>
