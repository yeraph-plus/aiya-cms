<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { archiveTerm, createTerm, fetchDimensions, fetchTerms, updateTerm, type DimensionDTO, type TermDTO } from '@/api/taxonomy';
import { errorMessage } from '@/api/errors';
import { hasCapability } from '@/auth/session';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';
import PageState from '@/components/feedback/PageState.vue';
import PageToolbar from '@/components/data/PageToolbar.vue';

const dimensions = ref<DimensionDTO[]>([]);
const terms = ref<TermDTO[]>([]);
const selectedDimension = ref<string | null>(null);
const loading = ref(false);
const termsLoading = ref(false);
const error = ref<unknown>(null);
const termsError = ref<unknown>(null);
const dialogVisible = ref(false);
const saving = ref(false);
const editingTerm = ref<TermDTO | null>(null);
const formError = ref<unknown>(null);
const form = reactive({ name: '', slug: '', description: '' });
const canManage = computed(() => hasCapability('taxonomy.manage'));
const dialogTitle = computed(() => (editingTerm.value ? 'Edit term' : 'New term'));

async function loadDimensions(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        dimensions.value = await fetchDimensions();
        selectedDimension.value = selectedDimension.value ?? dimensions.value[0]?.dimension_key ?? null;
        await loadTerms();
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

async function loadTerms(): Promise<void> {
    if (!selectedDimension.value) {
        terms.value = [];
        return;
    }
    termsLoading.value = true;
    termsError.value = null;
    try {
        terms.value = await fetchTerms(selectedDimension.value);
    } catch (caught) {
        termsError.value = caught;
    } finally {
        termsLoading.value = false;
    }
}

function selectDimension(): void {
    void loadTerms();
}

function openNew(): void {
    editingTerm.value = null;
    form.name = '';
    form.slug = '';
    form.description = '';
    formError.value = null;
    dialogVisible.value = true;
}

function openEdit(term: TermDTO): void {
    editingTerm.value = term;
    form.name = term.name;
    form.slug = term.slug;
    form.description = term.description ?? '';
    formError.value = null;
    dialogVisible.value = true;
}

async function saveTerm(): Promise<void> {
    if (!selectedDimension.value) return;
    saving.value = true;
    formError.value = null;
    try {
        if (editingTerm.value) {
            await updateTerm(editingTerm.value.id, {
                name: form.name,
                description: form.description || null
            });
        } else {
            await createTerm(selectedDimension.value, {
                name: form.name,
                slug: form.slug,
                description: form.description || null
            });
        }
        dialogVisible.value = false;
        await loadTerms();
    } catch (caught) {
        formError.value = caught;
    } finally {
        saving.value = false;
    }
}

async function archive(term: TermDTO): Promise<void> {
    try {
        await archiveTerm(term.id);
        await loadTerms();
    } catch (caught) {
        termsError.value = caught;
    }
}

onMounted(() => {
    void loadDimensions();
});
</script>

<template>
    <PageToolbar title="Taxonomy" subtitle="Manage flat dimensions and terms used by post content.">
        <template #actions>
            <Button icon="pi pi-refresh" label="Refresh" severity="secondary" :loading="loading || termsLoading" @click="loadDimensions" />
            <Button v-if="canManage" icon="pi pi-plus" label="New term" :disabled="!selectedDimension" @click="openNew" />
        </template>

        <PageState v-if="loading" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" description="Taxonomy dimensions could not be loaded." />
        <template v-else>
            <div class="card flex flex-wrap items-end gap-4">
                <div class="flex min-w-64 flex-col gap-2">
                    <label for="taxonomy-dimension" class="font-medium">Dimension</label>
                    <Select id="taxonomy-dimension" v-model="selectedDimension" :options="dimensions" option-label="display_name" option-value="dimension_key" @change="selectDimension" />
                </div>
                <div v-if="selectedDimension" class="text-sm text-muted-color">{{ dimensions.find((dimension) => dimension.dimension_key === selectedDimension)?.selection_mode }} selection</div>
            </div>

            <Message v-if="termsError" severity="error" :closable="false">{{ errorMessage(termsError) }}</Message>
            <PageState v-else-if="termsLoading" state="loading" />
            <PageState v-else-if="terms.length === 0" state="empty" title="No terms" description="Create the first term for this dimension." />
            <div v-else class="card">
                <DataTable :value="terms" :loading="termsLoading" responsive-layout="scroll">
                    <Column field="name" header="Name" style="min-width: 14rem" />
                    <Column field="slug" header="Slug" style="min-width: 12rem" />
                    <Column field="status" header="Status" style="min-width: 8rem">
                        <template #body="{ data }"><Tag :value="data.status" :severity="data.status === 'active' ? 'success' : 'secondary'" /></template>
                    </Column>
                    <Column field="description" header="Description" style="min-width: 18rem">
                        <template #body="{ data }">{{ data.description || '-' }}</template>
                    </Column>
                    <Column header="Actions" style="width: 12rem">
                        <template #body="{ data }">
                            <div class="flex flex-wrap gap-1">
                                <Button v-if="canManage && data.status === 'active'" label="Edit" text icon="pi pi-pencil" @click="openEdit(data)" />
                                <ConfirmAction v-if="canManage && data.status === 'active'" label="Archive" severity="warn" message="Archive this term? Existing assignments remain readable but cannot select it again." @confirmed="archive(data)" />
                            </div>
                        </template>
                    </Column>
                </DataTable>
            </div>
        </template>

        <Dialog v-model:visible="dialogVisible" :header="dialogTitle" modal class="w-full max-w-xl">
            <form class="flex flex-col gap-4" @submit.prevent="saveTerm">
                <Message v-if="formError" severity="error" :closable="false">{{ errorMessage(formError) }}</Message>
                <div class="flex flex-col gap-2">
                    <label for="term-name" class="font-medium">Name</label>
                    <InputText id="term-name" v-model="form.name" required maxlength="200" />
                </div>
                <div class="flex flex-col gap-2">
                    <label for="term-slug" class="font-medium">Slug</label>
                    <InputText id="term-slug" v-model="form.slug" :disabled="!!editingTerm" required maxlength="200" />
                </div>
                <div class="flex flex-col gap-2">
                    <label for="term-description" class="font-medium">Description</label>
                    <Textarea id="term-description" v-model="form.description" rows="4" auto-resize maxlength="1000" />
                </div>
                <div class="flex justify-end gap-2">
                    <Button type="button" label="Cancel" severity="secondary" text @click="dialogVisible = false" />
                    <Button type="submit" label="Save" icon="pi pi-check" :loading="saving" />
                </div>
            </form>
        </Dialog>
    </PageToolbar>
</template>
