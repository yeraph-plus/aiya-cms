<script setup lang="ts">
withDefaults(
    defineProps<{
        value: unknown[];
        loading?: boolean;
        totalRecords?: number;
        page?: number;
        size?: number;
        rowsOptions?: number[];
    }>(),
    {
        loading: false,
        totalRecords: 0,
        page: 1,
        size: 10,
        rowsOptions: () => [10, 25, 50]
    }
);

const emit = defineEmits<{
    'update:page': [value: number];
    'update:size': [value: number];
}>();

const onPage = (event: { page: number; rows: number }) => {
    emit('update:page', event.page + 1);
    emit('update:size', event.rows);
};
</script>

<template>
    <DataTable :value="value" :loading="loading" lazy :total-records="totalRecords" :rows="size" :first="(page - 1) * size" :rows-per-page-options="rowsOptions" @page="onPage">
        <template #empty>
            <EmptyTable />
        </template>
        <slot />
    </DataTable>
</template>
