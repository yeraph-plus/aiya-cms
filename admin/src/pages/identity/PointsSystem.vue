<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';
import { createPointsProgram, fetchPointsAccounts, fetchPointsPrograms, fetchPointsSummary, setPointsProgramStatus, updatePointsProgram, type PointsAccountPageDTO, type PointsProgramDTO, type PointsSummaryDTO } from '@/api/points';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t } = useI18n();
const router = useRouter();
const canAdjust = computed(() => hasCapability('points.adjust'));
const canManage = computed(() => hasCapability('points.programs.manage'));
const programs = ref<PointsProgramDTO[]>([]);
const summary = ref<PointsSummaryDTO | null>(null);
const accounts = ref<PointsAccountPageDTO | null>(null);
const loading = ref(false);
const error = ref<unknown>(null);
const dialogVisible = ref(false);
const dialogLoading = ref(false);
const dialogError = ref<unknown>(null);
const editing = ref<PointsProgramDTO | null>(null);
const form = reactive({
    program_key: '',
    display_name: '',
    unit: 'points',
    allow_admin_reversal: true
});

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        const [nextPrograms, nextSummary, nextAccounts] = await Promise.all([fetchPointsPrograms(), fetchPointsSummary(), fetchPointsAccounts({ page: 1, size: 10 })]);
        programs.value = nextPrograms;
        summary.value = nextSummary;
        accounts.value = nextAccounts;
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function openUsers(): void {
    void router.push('/users');
}

function openCreate(): void {
    editing.value = null;
    Object.assign(form, {
        program_key: '',
        display_name: '',
        unit: 'points',
        allow_admin_reversal: true
    });
    dialogError.value = null;
    dialogVisible.value = true;
}

function openEdit(program: PointsProgramDTO): void {
    editing.value = program;
    Object.assign(form, {
        program_key: program.program_key,
        display_name: program.display_name,
        unit: program.unit,
        allow_admin_reversal: program.allow_admin_reversal
    });
    dialogError.value = null;
    dialogVisible.value = true;
}

async function saveProgram(): Promise<void> {
    if (!form.display_name.trim() || !form.unit.trim() || (!editing.value && !form.program_key.trim())) return;
    dialogLoading.value = true;
    dialogError.value = null;
    try {
        const saved = editing.value
            ? await updatePointsProgram(editing.value.program_key, {
                  display_name: form.display_name.trim(),
                  unit: form.unit.trim(),
                  allow_admin_reversal: form.allow_admin_reversal,
                  expected_version: editing.value.version
              })
            : await createPointsProgram({
                  program_key: form.program_key.trim(),
                  display_name: form.display_name.trim(),
                  unit: form.unit.trim(),
                  allow_admin_reversal: form.allow_admin_reversal
              });
        programs.value = editing.value ? programs.value.map((item) => (item.program_key === saved.program_key ? saved : item)) : [...programs.value, saved];
        dialogVisible.value = false;
    } catch (caught) {
        dialogError.value = caught;
    } finally {
        dialogLoading.value = false;
    }
}

async function toggleProgram(program: PointsProgramDTO): Promise<void> {
    try {
        const saved = await setPointsProgramStatus(program.program_key, program.status === 'active' ? 'deactivate' : 'activate', undefined, program.version);
        programs.value = programs.value.map((item) => (item.program_key === saved.program_key ? saved : item));
    } catch (caught) {
        error.value = caught;
    }
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.users.points')" :description="t('workbenches.points.description')" :loading="loading" @refresh="load">
        <template #actions>
            <Button v-if="canManage" :label="t('workbenches.points.createProgram')" icon="pi pi-plus" @click="openCreate" />
        </template>
        <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
            <SurfaceCard v-for="program in programs" :key="program.program_key" :title="program.display_name" :description="program.program_key">
                <div class="mb-3 flex items-center gap-2">
                    <StatusTag :value="program.status" /><span class="text-sm text-muted-color">{{ program.unit }}</span>
                </div>
                <p class="text-muted-color mb-3 mt-2 text-sm">
                    {{ t('workbenches.points.catalogDescription') }}
                </p>
                <div v-if="canManage" class="flex gap-2">
                    <Button text size="small" :label="t('common.edit')" @click="openEdit(program)" /><Button
                        text
                        size="small"
                        :severity="program.status === 'active' ? 'warn' : 'success'"
                        :label="program.status === 'active' ? t('workbenches.points.deactivate') : t('workbenches.points.activate')"
                        @click="toggleProgram(program)"
                    />
                </div>
            </SurfaceCard>
            <SurfaceCard v-if="programs.length === 0 && !loading" :title="t('workbenches.points.program')"
                ><p class="text-muted-color mb-0">
                    {{ t('workbenches.points.emptyPrograms') }}
                </p></SurfaceCard
            >
            <SurfaceCard :title="t('workbenches.points.accountCount')">
                <strong class="text-2xl">{{ summary?.account_count ?? '—' }}</strong>
                <p class="text-muted-color mb-0 mt-2 text-sm">
                    {{ summary ? `${summary.active_account_count} active · ${summary.frozen_account_count} frozen · ${summary.debt_account_count} debt` : t('workbenches.points.accountCountHint') }}
                </p>
            </SurfaceCard>
            <SurfaceCard :title="t('workbenches.points.operations')">
                <p class="text-muted-color mb-3 text-sm">
                    {{ t('workbenches.points.operationsHint') }}
                </p>
                <Button :label="t('users.openList')" icon="pi pi-users" :disabled="!canAdjust" @click="openUsers" />
            </SurfaceCard>
        </div>
        <SurfaceCard v-if="accounts" class="mt-4" :title="t('workbenches.points.accounts')" :description="`${accounts.total}`">
            <DataTable :value="accounts.items" size="small" striped-rows>
                <Column field="program_key" :header="t('workbenches.points.program')" />
                <Column field="subject_id" :header="t('workbenches.subjectId')">
                    <template #body="{ data }">
                        <div>
                            {{ data.subject?.display_name || data.subject?.username || data.subject_id }}
                        </div>
                        <small v-if="data.subject?.display_name || data.subject?.username" class="text-muted-color">{{ data.subject_id }}</small>
                    </template>
                </Column>
                <Column field="balance" :header="t('workbenches.points.balance')" />
                <Column field="state" :header="t('workbenches.status')"
                    ><template #body="{ data }"><StatusTag :value="data.state" /></template
                ></Column>
            </DataTable>
        </SurfaceCard>
        <ApiErrorMessage v-if="error" :error="error" />
        <Message severity="info" :closable="false">{{ t('workbenches.points.userDrawerHint') }}</Message>

        <FormDialogShell v-model="dialogVisible" :title="editing ? t('workbenches.points.editProgram') : t('workbenches.points.createProgram')">
            <ApiErrorMessage v-if="dialogError" :error="dialogError" />
            <div class="flex flex-col gap-3">
                <label v-if="!editing" class="flex flex-col gap-1"
                    ><span>{{ t('workbenches.points.programKey') }}</span
                    ><InputText v-model="form.program_key"
                /></label>
                <label class="flex flex-col gap-1"
                    ><span>{{ t('workbenches.points.programName') }}</span
                    ><InputText v-model="form.display_name"
                /></label>
                <label class="flex flex-col gap-1"
                    ><span>{{ t('workbenches.points.unit') }}</span
                    ><InputText v-model="form.unit"
                /></label>
                <label class="flex items-center gap-2"
                    ><Checkbox v-model="form.allow_admin_reversal" binary /><span>{{ t('workbenches.points.allowReversal') }}</span></label
                >
            </div>
            <template #footer><Button :label="t('common.save')" :loading="dialogLoading" @click="saveProgram" /></template>
        </FormDialogShell>
    </PageShell>
</template>
