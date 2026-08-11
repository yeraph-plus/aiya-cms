<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { disableOidcClient, enableOidcClient, fetchOidcClients, registerOidcClient, rotateOidcClientSecret, updateOidcClient, type ClientDTO } from '@/api/oidc-admin';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t } = useI18n();
const clients = ref<ClientDTO[] | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref<unknown>(null);
const actionError = ref<unknown>(null);
const formVisible = ref(false);
const selected = ref<ClientDTO | null>(null);
const oneTimeSecret = ref<string | null>(null);
const canManage = computed(() => hasCapability('oidc_provider.clients.manage'));
const form = reactive({
    clientId: '',
    name: '',
    clientType: 'public',
    redirectUris: '',
    postLogoutUris: '',
    scopes: 'openid\nprofile\nemail',
    audiences: '',
    trusted: false,
    allowRefresh: true
});

function lines(value: string): string[] {
    return value.split(/\r?\n/u).map((item) => item.trim()).filter(Boolean);
}

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        clients.value = await fetchOidcClients();
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function openCreate(): void {
    selected.value = null;
    Object.assign(form, { clientId: '', name: '', clientType: 'public', redirectUris: '', postLogoutUris: '', scopes: 'openid\nprofile\nemail', audiences: '', trusted: false, allowRefresh: true });
    actionError.value = null;
    oneTimeSecret.value = null;
    formVisible.value = true;
}

function openEdit(client: ClientDTO): void {
    selected.value = client;
    Object.assign(form, {
        clientId: client.client_id,
        name: client.name,
        clientType: client.client_type,
        redirectUris: client.redirect_uris.join('\n'),
        postLogoutUris: (client.post_logout_redirect_uris ?? []).join('\n'),
        scopes: client.allowed_scopes.join('\n'),
        audiences: (client.allowed_audiences ?? []).join('\n'),
        trusted: client.trusted,
        allowRefresh: client.allow_refresh
    });
    actionError.value = null;
    oneTimeSecret.value = null;
    formVisible.value = true;
}

function replaceClient(client: ClientDTO): void {
    clients.value = (clients.value ?? []).some((item) => item.client_id === client.client_id) ? (clients.value ?? []).map((item) => (item.client_id === client.client_id ? client : item)) : [...(clients.value ?? []), client];
}

async function save(): Promise<void> {
    saving.value = true;
    actionError.value = null;
    try {
        if (selected.value) {
            const updated = await updateOidcClient(selected.value.client_id, {
                redirect_uris: lines(form.redirectUris),
                post_logout_redirect_uris: lines(form.postLogoutUris),
                allowed_scopes: lines(form.scopes),
                allowed_audiences: lines(form.audiences)
            });
            replaceClient(updated);
            formVisible.value = false;
        } else {
            const created = await registerOidcClient({
                name: form.name.trim(),
                client_type: form.clientType,
                client_id: form.clientId.trim() || null,
                redirect_uris: lines(form.redirectUris),
                post_logout_redirect_uris: lines(form.postLogoutUris),
                allowed_scopes: lines(form.scopes),
                allowed_audiences: lines(form.audiences),
                trusted: form.trusted,
                allow_refresh: form.allowRefresh
            });
            replaceClient(created.client);
            oneTimeSecret.value = created.client_secret ?? null;
            if (!oneTimeSecret.value) formVisible.value = false;
        }
    } catch (caught) {
        actionError.value = caught;
    } finally {
        saving.value = false;
    }
}

async function toggleStatus(client: ClientDTO): Promise<void> {
    actionError.value = null;
    try {
        replaceClient(client.status === 'active' ? await disableOidcClient(client.client_id) : await enableOidcClient(client.client_id));
    } catch (caught) {
        actionError.value = caught;
    }
}

async function rotateSecret(client: ClientDTO): Promise<void> {
    actionError.value = null;
    saving.value = true;
    try {
        const result = await rotateOidcClientSecret(client.client_id);
        oneTimeSecret.value = result.client_secret ?? null;
        selected.value = client;
        formVisible.value = true;
    } catch (caught) {
        actionError.value = caught;
    } finally {
        saving.value = false;
    }
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.system.oidc')" :description="t('workbenches.oidc.description')" :loading="loading" @refresh="load">
        <template #actions><Button v-if="canManage" icon="pi pi-plus" :label="t('workbenches.oidc.register')" @click="openCreate" /></template>
        <ApiErrorMessage v-if="actionError && !formVisible" :error="actionError" />
        <PageState v-if="loading && !clients" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="clients?.length === 0" state="empty" :title="t('workbenches.oidc.empty')" />
        <div v-else class="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <SurfaceCard v-for="client in clients" :key="client.client_id" :title="client.name" :description="client.client_id">
                <template #actions><Tag :value="client.status" :severity="client.status === 'active' ? 'success' : 'secondary'" /></template>
                <div class="mb-4 flex flex-wrap gap-2"><Tag :value="client.client_type" /><Tag v-for="scope in client.allowed_scopes" :key="scope" :value="scope" severity="secondary" /></div>
                <ul class="mb-4 list-disc pl-5 text-sm"><li v-for="uri in client.redirect_uris" :key="uri" class="break-all">{{ uri }}</li></ul>
                <div v-if="canManage" class="flex flex-wrap gap-2">
                    <Button :label="t('common.edit')" severity="secondary" @click="openEdit(client)" />
                    <Button :label="client.status === 'active' ? t('workbenches.oidc.disable') : t('workbenches.oidc.enable')" :severity="client.status === 'active' ? 'warn' : 'success'" @click="toggleStatus(client)" />
                    <Button v-if="client.client_type === 'confidential'" :label="t('workbenches.oidc.rotateSecret')" severity="danger" @click="rotateSecret(client)" />
                </div>
            </SurfaceCard>
        </div>

        <FormDialogShell v-model="formVisible" :title="selected ? t('workbenches.oidc.edit') : t('workbenches.oidc.register')" width-class="w-full max-w-3xl">
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <Message v-if="oneTimeSecret" severity="warn" :closable="false">
                {{ t('workbenches.oidc.secretOnce') }}
                <pre class="mt-3 whitespace-pre-wrap break-all select-all">{{ oneTimeSecret }}</pre>
            </Message>
            <form v-else class="grid grid-cols-1 gap-4 md:grid-cols-2" @submit.prevent="save">
                <InputText v-if="!selected" v-model="form.clientId" :placeholder="t('workbenches.oidc.clientIdOptional')" />
                <InputText v-if="!selected" v-model="form.name" :placeholder="t('workbenches.oidc.name')" required />
                <Select v-if="!selected" v-model="form.clientType" :options="['public', 'confidential']" />
                <Textarea v-model="form.redirectUris" rows="4" :placeholder="t('workbenches.oidc.redirectUris')" class="md:col-span-2" required />
                <Textarea v-model="form.postLogoutUris" rows="3" :placeholder="t('workbenches.oidc.postLogoutUris')" />
                <Textarea v-model="form.scopes" rows="3" :placeholder="t('workbenches.oidc.scopes')" />
                <Textarea v-model="form.audiences" rows="3" :placeholder="t('workbenches.oidc.audiences')" />
                <div v-if="!selected" class="flex flex-col gap-3"><label><Checkbox v-model="form.trusted" binary /> {{ t('workbenches.oidc.trusted') }}</label><label><Checkbox v-model="form.allowRefresh" binary /> {{ t('workbenches.oidc.allowRefresh') }}</label></div>
                <Button type="submit" :label="t('workbenches.save')" :loading="saving" class="md:col-span-2" />
            </form>
        </FormDialogShell>
    </PageShell>
</template>
