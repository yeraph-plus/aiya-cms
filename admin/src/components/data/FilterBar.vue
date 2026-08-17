<script setup lang="ts">
withDefaults(defineProps<{ label: string; layoutClass?: string }>(), {
    layoutClass: 'flex flex-wrap items-end gap-4'
});
defineEmits<{ submit: [] }>();
</script>

<template>
    <form :class="layoutClass" @submit.prevent="$emit('submit')">
        <slot />
        <slot name="actions" />
        <Button type="submit" icon="pi pi-search" :label="label" />
    </form>
</template>
