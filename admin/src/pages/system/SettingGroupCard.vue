<script setup lang="ts">
import { ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useToast } from 'primevue/usetoast';
import { createUploadIntent, finalizeUpload, uploadToProvider, waitForAsset } from '@/api/assets';
import { resetSettingGroup, updateSettingGroup, type SettingGroupDTO } from '@/api/settings';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';
import SettingField from '@/components/forms/SettingField.vue';
import { editableSettingValues, type SettingValues } from '@/components/forms/setting-fields';
import { hasCapability } from '@/auth/session';

const { t, locale } = useI18n();
const props = defineProps<{ group: SettingGroupDTO }>();

const emit = defineEmits<{
    updated: [group: SettingGroupDTO];
}>();

const toast = useToast();
const values = ref<SettingValues>({});
const clearSensitiveFields = ref<Set<string>>(new Set());
const saving = ref(false);
const actionError = ref<unknown>(null);
const uploadError = ref<Error | null>(null);

const canUpdate = () => hasCapability('settings.update') || hasCapability(`settings.${props.group.group_key}.update`);

function syncValues(group: SettingGroupDTO): void {
    values.value = editableSettingValues(group.values);
    clearSensitiveFields.value = new Set();
    actionError.value = null;
    uploadError.value = null;
}

async function save(): Promise<void> {
    if (!canUpdate()) return;
    saving.value = true;
    actionError.value = null;
    try {
        const updated = await updateSettingGroup(props.group.group_key, {
            expected_version: props.group.version,
            values: values.value,
            clear_sensitive_fields: [...clearSensitiveFields.value]
        });
        emit('updated', updated);
        toast.add({
            severity: 'success',
            summary: t('workbenches.settings.saved'),
            detail: t('workbenches.settings.savedDetail'),
            life: 3000
        });
    } catch (caught) {
        actionError.value = caught;
    } finally {
        saving.value = false;
    }
}

function updateField(slug: string, value: import('@/components/forms/setting-fields').SettingValue): void {
    values.value[slug] = value;
    clearSensitiveFields.value.delete(slug);
}

function clearSensitiveField(slug: string): void {
    delete values.value[slug];
    clearSensitiveFields.value.add(slug);
}

async function reset(): Promise<void> {
    if (!canUpdate()) return;
    saving.value = true;
    actionError.value = null;
    try {
        const updated = await resetSettingGroup(props.group.group_key);
        emit('updated', updated);
        toast.add({
            severity: 'success',
            summary: t('workbenches.settings.resetDone'),
            detail: t('workbenches.settings.resetDoneDetail'),
            life: 3000
        });
    } catch (caught) {
        actionError.value = caught;
    } finally {
        saving.value = false;
    }
}

async function uploadAsset(file: File): Promise<string> {
    const intent = await createUploadIntent({
        provider_key: 's3',
        mime_types: [file.type || 'application/octet-stream'],
        content_length_max: file.size
    });
    await uploadToProvider(intent, file);
    await finalizeUpload(intent.intent_id);
    const asset = await waitForAsset(intent.object_key);
    return asset.id;
}

watch(() => props.group, syncValues, { immediate: true });
</script>

<template>
    <Card>
        <template #title>{{ group.group_key }}</template>
        <template #subtitle>Schema {{ group.schema_version }} · Version {{ group.version }}</template>
        <template #content>
            <div class="grid grid-cols-12 gap-6">
                <div v-for="field in group.fields" :key="field.slug" class="col-span-12 md:col-span-6">
                    <SettingField
                        :model-value="values[field.slug]"
                        :field="field"
                        :group-key="group.group_key"
                        :sensitive-configured="group.sensitive_configured?.[field.slug] === true && !clearSensitiveFields.has(field.slug)"
                        :disabled="!canUpdate() || saving"
                        :upload-asset="uploadAsset"
                        @update:model-value="updateField(field.slug, $event)"
                        @clear-sensitive="clearSensitiveField(field.slug)"
                        @upload-error="uploadError = $event"
                    />
                </div>
            </div>

            <ApiErrorMessage v-if="actionError" class="mt-6" :error="actionError" />
            <Message v-if="uploadError" class="mt-6" severity="warn" :closable="false">{{ uploadError.message }}</Message>
            <Message v-if="!canUpdate()" class="mt-6" severity="info" :closable="false">{{ t('workbenches.settings.readOnly') }}</Message>
        </template>
        <template #footer>
            <div class="flex flex-wrap items-center justify-between gap-3 w-full">
                <span v-if="group.updated_at" class="text-sm text-muted-color">{{
                    t('workbenches.settings.lastUpdated', {
                        time: new Intl.DateTimeFormat(locale, {
                            dateStyle: 'medium',
                            timeStyle: 'short'
                        }).format(new Date(group.updated_at))
                    })
                }}</span>
                <span v-else class="text-sm text-muted-color">{{ t('workbenches.settings.notPersisted') }}</span>
                <div class="flex flex-wrap gap-2">
                    <ConfirmAction :label="t('workbenches.settings.reset')" :header="t('workbenches.settings.resetTitle')" :message="t('workbenches.settings.resetConfirm')" :disabled="!canUpdate() || saving" @confirmed="reset" />
                    <Button :label="t('common.save')" icon="pi pi-save" :loading="saving" :disabled="!canUpdate()" @click="save" />
                </div>
            </div>
        </template>
    </Card>
</template>
