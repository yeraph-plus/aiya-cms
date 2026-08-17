<script setup lang="ts">
withDefaults(
    defineProps<{
        title: string;
        description?: string;
        widthClass?: string;
    }>(),
    {
        description: '',
        widthClass: 'w-full max-w-xl'
    }
);

const visible = defineModel<boolean>({ required: true });
</script>

<template>
    <Dialog v-model:visible="visible" :header="title" modal :class="widthClass">
        <p v-if="description" class="text-muted-color mt-0 text-sm">
            {{ description }}
        </p>
        <slot />
        <template v-if="$slots.footer" #footer><slot name="footer" /></template>
    </Dialog>
</template>
