<script setup lang="ts">
import FormDialogShell from './FormDialogShell.vue';
import { useI18n } from 'vue-i18n';

withDefaults(
    defineProps<{
        title: string;
        message: string;
        confirmLabel: string;
        loading?: boolean;
        disabled?: boolean;
    }>(),
    {
        loading: false,
        disabled: false
    }
);

const visible = defineModel<boolean>({ required: true });
defineEmits<{ confirm: [] }>();
const { t } = useI18n();
</script>

<template>
    <FormDialogShell v-model="visible" :title="title">
        <Message severity="warn" :closable="false">{{ message }}</Message>
        <slot />
        <template #footer>
            <Button :label="t('common.cancel')" severity="secondary" text :disabled="loading" @click="visible = false" />
            <Button :label="confirmLabel" severity="danger" :loading="loading" :disabled="disabled" @click="$emit('confirm')" />
        </template>
    </FormDialogShell>
</template>
