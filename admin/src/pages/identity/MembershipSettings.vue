<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { createMembershipLevel, fetchMembershipLevels, setMembershipLevelStatus, updateMembershipLevel, type CreateLevelInput, type LevelDTO } from '@/api/membership';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import FormDialogShell from '@/components/shell/FormDialogShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import PageState from '@/components/feedback/PageState.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t } = useI18n();
const canManage = computed(() => hasCapability('membership.levels.manage'));
const levels = ref<LevelDTO[]>([]);
const loading = ref(false);
const error = ref<unknown>(null);
const dialogVisible = ref(false);
const dialogLoading = ref(false);
const dialogError = ref<unknown>(null);
const editing = ref<LevelDTO | null>(null);
const form = reactive<CreateLevelInput>({
    level_key: '',
    display_name: '',
    tier_rank: 1,
    cycle_days: 30,
    grant_points: 100,
    renewal_allowed: true
});

async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
        levels.value = await fetchMembershipLevels();
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

function openCreate(): void {
    editing.value = null;
    Object.assign(form, {
        level_key: '',
        display_name: '',
        tier_rank: 1,
        cycle_days: 30,
        grant_points: 100,
        renewal_allowed: true
    });
    dialogError.value = null;
    dialogVisible.value = true;
}

function openEdit(level: LevelDTO): void {
    editing.value = level;
    Object.assign(form, {
        level_key: level.level_key,
        display_name: level.display_name,
        tier_rank: level.tier_rank,
        cycle_days: level.cycle_days,
        grant_points: level.grant_points,
        renewal_allowed: level.renewal_allowed
    });
    dialogError.value = null;
    dialogVisible.value = true;
}

async function save(): Promise<void> {
    if (!form.display_name.trim() || (!editing.value && !form.level_key.trim())) return;
    dialogLoading.value = true;
    dialogError.value = null;
    try {
        const saved = editing.value
            ? await updateMembershipLevel(editing.value.level_key, {
                  display_name: form.display_name.trim(),
                  tier_rank: form.tier_rank,
                  cycle_days: form.cycle_days,
                  grant_points: form.grant_points,
                  renewal_allowed: form.renewal_allowed,
                  expected_version: editing.value.version
              })
            : await createMembershipLevel({
                  ...form,
                  level_key: form.level_key.trim(),
                  display_name: form.display_name.trim()
              });
        levels.value = editing.value ? levels.value.map((item) => (item.level_key === saved.level_key ? saved : item)) : [...levels.value, saved];
        dialogVisible.value = false;
    } catch (caught) {
        dialogError.value = caught;
    } finally {
        dialogLoading.value = false;
    }
}

async function toggle(level: LevelDTO): Promise<void> {
    try {
        const saved = await setMembershipLevelStatus(level.level_key, level.status === 'active' ? 'archive' : 'activate', undefined, level.version);
        levels.value = levels.value.map((item) => (item.level_key === saved.level_key ? saved : item));
    } catch (caught) {
        error.value = caught;
    }
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('nav.settingsMembership')" :description="t('workbenches.membership.settingsDescription')" :loading="loading" @refresh="load">
        <template #actions><Button v-if="canManage" :label="t('workbenches.membership.createLevel')" icon="pi pi-plus" @click="openCreate" /></template>
        <PageState v-if="loading && levels.length === 0" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <SurfaceCard v-for="level in levels" :key="level.level_key" :title="level.display_name" :description="level.level_key">
                <dl class="grid grid-cols-2 gap-2 text-sm">
                    <dt class="text-muted-color">
                        {{ t('workbenches.membership.tier') }}
                    </dt>
                    <dd>{{ level.tier_rank }}</dd>
                    <dt class="text-muted-color">
                        {{ t('workbenches.membership.cycle') }}
                    </dt>
                    <dd>
                        {{ t('workbenches.membership.days', { count: level.cycle_days }) }}
                    </dd>
                    <dt class="text-muted-color">
                        {{ t('workbenches.membership.points') }}
                    </dt>
                    <dd>{{ level.grant_points }}</dd>
                    <dt class="text-muted-color">{{ t('workbenches.status') }}</dt>
                    <dd><StatusTag :value="level.status" /></dd>
                </dl>
                <div v-if="canManage" class="mt-3 flex gap-2">
                    <Button text size="small" :label="t('common.edit')" @click="openEdit(level)" /><Button
                        text
                        size="small"
                        :severity="level.status === 'active' ? 'warn' : 'success'"
                        :label="level.status === 'active' ? t('workbenches.membership.archiveLevel') : t('workbenches.membership.activateLevel')"
                        @click="toggle(level)"
                    />
                </div>
            </SurfaceCard>
            <SurfaceCard v-if="levels.length === 0" :title="t('nav.settingsMembership')"
                ><p class="text-muted-color mb-0">
                    {{ t('workbenches.membership.emptyLevels') }}
                </p></SurfaceCard
            >
        </div>
        <FormDialogShell v-model="dialogVisible" :title="editing ? t('workbenches.membership.editLevel') : t('workbenches.membership.createLevel')">
            <ApiErrorMessage v-if="dialogError" :error="dialogError" />
            <div class="flex flex-col gap-3">
                <label v-if="!editing" class="flex flex-col gap-1"
                    ><span>{{ t('workbenches.membership.levelKey') }}</span
                    ><InputText v-model="form.level_key"
                /></label>
                <label class="flex flex-col gap-1"
                    ><span>{{ t('workbenches.membership.displayName') }}</span
                    ><InputText v-model="form.display_name"
                /></label>
                <label class="flex flex-col gap-1"
                    ><span>{{ t('workbenches.membership.tierRank') }}</span
                    ><InputNumber v-model="form.tier_rank" :min="1"
                /></label>
                <label class="flex flex-col gap-1"
                    ><span>{{ t('workbenches.membership.cycleDays') }}</span
                    ><InputNumber v-model="form.cycle_days" :min="1"
                /></label>
                <label class="flex flex-col gap-1"
                    ><span>{{ t('workbenches.membership.grantPoints') }}</span
                    ><InputNumber v-model="form.grant_points" :min="1"
                /></label>
                <label class="flex items-center gap-2"
                    ><Checkbox v-model="form.renewal_allowed" binary /><span>{{ t('workbenches.membership.renewalAllowed') }}</span></label
                >
            </div>
            <template #footer><Button :label="t('common.save')" :loading="dialogLoading" @click="save" /></template>
        </FormDialogShell>
    </PageShell>
</template>
