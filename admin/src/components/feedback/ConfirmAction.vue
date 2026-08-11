<script setup lang="ts">
import { ref } from 'vue';
import SensitiveActionDialog from '@/components/shell/SensitiveActionDialog.vue';

const props = withDefaults(
    defineProps<{
        label: string;
        message: string;
        header?: string;
        severity?: 'info' | 'success' | 'warn' | 'danger' | 'secondary' | 'contrast' | 'help';
        disabled?: boolean;
    }>(),
    {
        header: 'Confirm',
        severity: 'danger',
        disabled: false
    }
);

const emit = defineEmits<{
    confirmed: [];
}>();

const visible = ref(false);

function confirm(): void {
    visible.value = false;
    emit('confirmed');
}
</script>

<template>
    <Button :label="label" :severity="severity" :disabled="disabled" @click="visible = true" />
    <SensitiveActionDialog v-model="visible" :title="header" :message="message" :confirm-label="label" :disabled="disabled" @confirm="confirm" />
</template>
