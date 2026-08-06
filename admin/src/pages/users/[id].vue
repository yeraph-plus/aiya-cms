<route lang="yaml">
meta:
  title: users
  authRequired: true
  requiredCapabilities:
    - user:read_any
</route>
<script setup lang="ts">
import { adminApi, type Role, type UserAdmin } from '~/common/api/admin-api'
const route = useRoute(); const router = useRouter(); const user = ref<UserAdmin | null>(null); const roles = ref<Role[]>([]); const selectedRoles = ref<string[]>([]); const displayName = ref(''); const avatarUrl = ref<string | null>(null); const roleOptions = computed(() => roles.value.map((role: Role) => ({ label: role.name, value: role.name }))); const loading = ref(true); const saving = ref(false); const error = ref('')
async function load() { try { const [loaded, roleList] = await Promise.all([adminApi.user(String(route.params.id)), adminApi.roles()]); user.value = loaded; roles.value = roleList; selectedRoles.value = [...loaded.roles]; displayName.value = loaded.display_name; avatarUrl.value = loaded.avatar_url } catch (err) { error.value = err instanceof Error ? err.message : 'Load failed' } finally { loading.value = false } }
async function saveProfile() { if (!user.value) return; saving.value = true; try { user.value = await adminApi.updateUser(user.value.id, { display_name: displayName.value, avatar_url: avatarUrl.value }) } catch (err) { error.value = err instanceof Error ? err.message : 'Save failed' } finally { saving.value = false } }
async function saveRoles() { if (!user.value || !window.confirm('Replace all roles?')) return; saving.value = true; try { user.value = await adminApi.replaceRoles(user.value.id, selectedRoles.value) } catch (err) { error.value = err instanceof Error ? err.message : 'Save failed' } finally { saving.value = false } }
async function changeStatus() { if (!user.value || !window.confirm('Confirm status change?')) return; saving.value = true; try { user.value = user.value.status === 'banned' ? await adminApi.unban(user.value.id) : await adminApi.ban(user.value.id) } catch (err) { error.value = err instanceof Error ? err.message : 'Action failed' } finally { saving.value = false } }
onMounted(load)
</script>
<template><n-spin :show="loading"><n-button class="mb-4" @click="router.back()">Back</n-button><n-alert v-if="error" type="error">{{ error }}</n-alert><n-card v-if="user" :bordered="false" class="rounded-lg"><template #header>{{ user.display_name }} ({{ user.username }})</template><div class="grid gap-3 md:grid-cols-2"><div><strong>Email</strong><p>{{ user.email }}</p></div><div><strong>Status</strong><p>{{ user.status }}</p></div><div><strong>Created</strong><p>{{ user.created_at }}</p></div></div><n-divider /><n-form label-placement="top"><n-form-item label="Display name"><n-input v-model:value="displayName" /></n-form-item><n-form-item label="Avatar URL"><n-input v-model:value="avatarUrl" clearable /></n-form-item><n-button type="primary" :loading="saving" @click="saveProfile">Save profile</n-button></n-form><n-divider /><n-form-item label="Roles"><n-select v-model:value="selectedRoles" multiple :options="roleOptions" /></n-form-item><n-button :loading="saving" @click="saveRoles">Replace roles</n-button><n-button class="ml-3" :type="user.status === 'banned' ? 'success' : 'warning'" :loading="saving" @click="changeStatus">{{ user.status === 'banned' ? 'Unban' : 'Ban' }}</n-button></n-card></n-spin></template>
