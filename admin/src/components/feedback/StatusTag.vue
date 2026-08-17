<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';

const props = withDefaults(defineProps<{ value: string | null | undefined }>(), { value: '' });
const { t, te } = useI18n();

const label = computed(() => {
    const value = props.value || 'unknown';
    const key = `statuses.${value}`;
    return te(key) ? t(key) : value;
});

const severity = computed<'success' | 'info' | 'warn' | 'danger' | 'secondary'>(() => {
    switch (props.value) {
        case 'active':
        case 'published':
        case 'ready':
        case 'delivered':
        case 'captured':
        case 'completed':
        case 'success':
        case 'refunded':
            return 'success';
        case 'pending':
        case 'scheduled':
        case 'sending':
        case 'created':
            return 'info';
        case 'failed':
        case 'rejected':
        case 'banned':
        case 'dead':
        case 'deleted':
        case 'failure':
            return 'danger';
        case 'archived':
        case 'cancelled':
        case 'inactive':
        case 'hidden':
        case 'frozen':
        case 'partially_refunded':
        case 'terminated':
        case 'expired':
        case 'debt':
            return 'warn';
        default:
            return 'secondary';
    }
});
</script>

<template>
    <Tag :value="label" :severity="severity" />
</template>
