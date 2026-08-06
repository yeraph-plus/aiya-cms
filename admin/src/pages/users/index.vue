<route lang="yaml">
meta:
  title: users
  authRequired: true
  requiredCapabilities:
    - user:read_any
</route>
<script setup lang="ts">
import { adminApi, type UserAdmin } from '~/common/api/admin-api'
const router = useRouter()
const q = ref('')
const status = ref('')
const page = ref(1)
const data = ref<UserAdmin[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
async function load() { loading.value = true; try { const result = await adminApi.users({ q: q.value, status: status.value, page: page.value, size: 20 }); data.value = result.items; total.value = result.total } catch (err) { error.value = err instanceof Error ? err.message : 'Load failed' } finally { loading.value = false } }
function openUser(id: string) { router.push(`/users/${id}`) }
watch([q, status, page], load)
onMounted(load)
</script>
<template>
  <n-card :bordered="false" class="rounded-lg">
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <n-input v-model:value="q" clearable placeholder="Search users" class="max-w-sm" />
      <n-select v-model:value="status" clearable placeholder="Status" :options="[{ label: 'Active', value: 'active' }, { label: 'Banned', value: 'banned' }, { label: 'Deleted', value: 'deleted' }]" class="w-36" />
      <n-button @click="load">Refresh</n-button>
    </div>
    <n-alert v-if="error" type="error" class="mb-4">{{ error }}</n-alert>
    <n-spin :show="loading">
      <n-empty v-if="!loading && !data.length" description="No users" />
      <n-table v-else striped :single-line="false">
        <thead><tr><th>Display name</th><th>Email</th><th>Status</th><th>Roles</th><th>Updated</th><th /></tr></thead>
        <tbody>
          <tr v-for="user in data" :key="user.id">
            <td>{{ user.display_name }} <small class="text-slate-400">@{{ user.username }}</small></td>
            <td>{{ user.email }}</td>
            <td>{{ user.status }}</td>
            <td>{{ user.roles.join(', ') || '-' }}</td>
            <td>{{ user.updated_at }}</td>
            <td><n-button text type="primary" @click="openUser(user.id)">Details</n-button></td>
          </tr>
        </tbody>
      </n-table>
      <div class="mt-4 flex justify-end"><n-pagination v-model:page="page" :page-size="20" :item-count="total" /></div>
    </n-spin>
  </n-card>
</template>
