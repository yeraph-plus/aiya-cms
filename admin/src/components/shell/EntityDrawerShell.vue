<script setup lang="ts">
withDefaults(
    defineProps<{
        title: string;
        description?: string;
        widthClass?: string;
    }>(),
    {
        description: '',
        widthClass: '!w-full md:!w-[48rem]'
    }
);

const visible = defineModel<boolean>({ required: true });
</script>

<template>
    <Drawer v-model:visible="visible" position="right" :class="widthClass">
        <template #header>
            <div>
                <h2 class="m-0 text-lg font-semibold">{{ title }}</h2>
                <p v-if="description" class="text-muted-color mb-0 mt-1 text-sm">{{ description }}</p>
            </div>
        </template>
        <slot />
        <template v-if="$slots.footer" #footer><slot name="footer" /></template>
    </Drawer>
</template>
