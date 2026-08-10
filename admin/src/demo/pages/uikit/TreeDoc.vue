<script setup lang="ts">
import { NodeService, type TreeNodeData } from '@/demo/services/NodeService';
import type { TreeSelectionKeys } from 'primevue/tree';
import type { TreeTableSelectionKeys } from 'primevue/treetable';
import { onMounted, ref } from 'vue';

const treeValue = ref<TreeNodeData[]>();
const selectedTreeValue = ref<TreeSelectionKeys>();
const treeTableValue = ref<TreeNodeData[]>();
const selectedTreeTableValue = ref<TreeTableSelectionKeys>();

onMounted(() => {
    NodeService.getTreeNodes().then((data) => (treeValue.value = data));
    NodeService.getTreeTableNodes().then((data) => (treeTableValue.value = data));
});
</script>

<template>
    <div class="card">
        <div class="font-semibold text-xl">Tree</div>
        <Tree :value="treeValue" selectionMode="checkbox" v-model:selectionKeys="selectedTreeValue"></Tree>
    </div>

    <div class="card">
        <div class="font-semibold text-xl mb-4">TreeTable</div>
        <TreeTable :value="treeTableValue" selectionMode="checkbox" v-model:selectionKeys="selectedTreeTableValue">
            <Column field="name" header="Name" :expander="true"></Column>
            <Column field="size" header="Size"></Column>
            <Column field="type" header="Type"></Column>
        </TreeTable>
    </div>
</template>
