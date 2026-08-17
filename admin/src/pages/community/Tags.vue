<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { archiveTag, createTag, fetchTags, reorderTags, restoreTag, updateTag, type CreateTagInput, type TagDTO } from '@/api/community';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';
import PageState from '@/components/feedback/PageState.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';
import PageShell from '@/components/shell/PageShell.vue';

const { t } = useI18n();
const tags = ref<TagDTO[]>([]);
const loading = ref(false);
const error = ref<unknown>(null);
const dialogVisible = ref(false);
const editing = ref<TagDTO | null>(null);
const saving = ref(false);
const formError = ref<unknown>(null);
const canManage = computed(() => hasCapability('community.tags.manage'));
const form = reactive({
    kind: 'primary' as CreateTagInput['kind'],
    name: '',
    slug: '',
    description: '',
    color: '',
    icon_key: ''
});

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        tags.value = await fetchTags(true);
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function openNew(): void {
    editing.value = null;
    form.kind = 'primary';
    form.name = '';
    form.slug = '';
    form.description = '';
    form.color = '';
    form.icon_key = '';
    formError.value = null;
    dialogVisible.value = true;
}

function openEdit(tag: TagDTO): void {
    editing.value = tag;
    form.kind = tag.kind as CreateTagInput['kind'];
    form.name = tag.name;
    form.slug = tag.slug;
    form.description = tag.description ?? '';
    form.color = tag.color ?? '';
    form.icon_key = tag.icon_key ?? '';
    formError.value = null;
    dialogVisible.value = true;
}

async function save(): Promise<void> {
    saving.value = true;
    formError.value = null;
    try {
        if (editing.value) {
            await updateTag(editing.value.id, {
                expected_version: editing.value.version,
                name: form.name,
                description: form.description || null,
                color: form.color || null,
                icon_key: form.icon_key || null,
                parent_id: editing.value.parent_id ? editing.value.parent_id : null,
                metadata: {}
            });
        } else {
            await createTag({
                kind: form.kind,
                name: form.name,
                slug: form.slug,
                description: form.description || null,
                color: form.color || null,
                icon_key: form.icon_key || null,
                parent_id: null,
                metadata: {}
            });
        }
        dialogVisible.value = false;
        await load();
    } catch (caught) {
        formError.value = caught;
    } finally {
        saving.value = false;
    }
}

async function restore(tag: TagDTO): Promise<void> {
    try {
        await restoreTag(tag.id);
        await load();
    } catch (caught) {
        error.value = caught;
    }
}

async function move(tag: TagDTO, delta: number): Promise<void> {
    const sameGroup = tags.value.filter((item) => item.kind === tag.kind && item.parent_id === tag.parent_id && item.status === 'active');
    const index = sameGroup.findIndex((item) => item.id === tag.id);
    const target = sameGroup[index + delta];
    if (!target) return;
    const next = [...sameGroup];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    try {
        await reorderTags({ tag_ids: next.map((item) => item.id) });
        await load();
    } catch (caught) {
        error.value = caught;
    }
}

async function archive(tag: TagDTO): Promise<void> {
    try {
        await archiveTag(tag.id);
        await load();
    } catch (caught) {
        error.value = caught;
    }
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.community.tags')" :description="t('workbenches.community.tags.description')" :loading="loading" @refresh="load">
        <template #actions><Button v-if="canManage" icon="pi pi-plus" :label="t('workbenches.community.tags.new')" @click="openNew" /></template>
        <PageState v-if="loading" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="tags.length === 0" state="empty" :title="t('workbenches.community.tags.empty')" />
        <div v-else class="surface-card">
            <DataTable :value="tags" responsive-layout="scroll">
                <Column field="name" :header="t('workbenches.community.tags.name')" />
                <Column field="slug" :header="t('workbenches.community.tags.slug')" />
                <Column field="kind" :header="t('workbenches.community.tags.kind')" />
                <Column field="position" :header="t('workbenches.community.tags.position')" />
                <Column field="published_discussion_count" :header="t('workbenches.community.tags.count')" />
                <Column field="status" :header="t('workbenches.status')"
                    ><template #body="{ data }"><StatusTag :value="data.status" /></template
                ></Column>
                <Column
                    ><template #body="{ data }"
                        ><div v-if="canManage" class="flex flex-wrap gap-1">
                            <Button text size="small" :label="t('common.edit')" @click="openEdit(data)" /><Button text size="small" icon="pi pi-arrow-up" aria-label="Move up" @click="move(data, -1)" /><Button
                                text
                                size="small"
                                icon="pi pi-arrow-down"
                                aria-label="Move down"
                                @click="move(data, 1)"
                            /><ConfirmAction v-if="data.status === 'active'" :label="t('workbenches.community.tags.archive')" severity="warn" :message="t('workbenches.community.tags.archiveConfirm')" @confirmed="archive(data)" /><Button
                                v-else
                                text
                                size="small"
                                severity="success"
                                :label="t('workbenches.community.tags.restore')"
                                @click="restore(data)"
                            /></div></template
                ></Column>
            </DataTable>
        </div>
        <FormDialogShell v-model="dialogVisible" :title="editing ? t('workbenches.community.tags.edit') : t('workbenches.community.tags.new')">
            <form class="flex flex-col gap-4" @submit.prevent="save">
                <ApiErrorMessage v-if="formError" :error="formError" />
                <Select v-model="form.kind" :options="['primary', 'secondary']" :placeholder="t('workbenches.community.tags.kind')" />
                <InputText v-model="form.name" :placeholder="t('workbenches.community.tags.name')" required maxlength="100" />
                <InputText v-model="form.slug" :placeholder="t('workbenches.community.tags.slug')" required maxlength="120" />
                <Textarea v-model="form.description" :placeholder="t('workbenches.description')" rows="3" maxlength="1000" />
                <InputText v-model="form.color" :placeholder="t('workbenches.community.tags.color')" maxlength="32" />
                <InputText v-model="form.icon_key" :placeholder="t('workbenches.community.tags.icon')" maxlength="64" />
                <div class="flex justify-end gap-2"><Button type="button" :label="t('common.cancel')" severity="secondary" text @click="dialogVisible = false" /><Button type="submit" :label="t('common.save')" :loading="saving" /></div>
            </form>
        </FormDialogShell>
    </PageShell>
</template>
