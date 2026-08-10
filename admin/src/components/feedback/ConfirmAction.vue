<script setup lang="ts">
import { useConfirm } from 'primevue/useconfirm';

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

const confirm = useConfirm();

const onConfirm = (event: Event) => {
    confirm.require({
        target: event.currentTarget as HTMLElement,
        message: props.message,
        header: props.header,
        accept: () => emit('confirmed')
    });
};
</script>

<template>
    <Button :label="label" :severity="severity" :disabled="disabled" @click="onConfirm" />
    <ConfirmPopup />
</template>
