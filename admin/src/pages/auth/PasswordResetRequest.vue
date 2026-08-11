<script setup lang="ts">
import { ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { requestPasswordReset } from '@/api/auth';
import AuthShell from '@/components/auth/AuthShell.vue';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';

const { t } = useI18n();
const identifier = ref('');
const submitting = ref(false);
const completed = ref(false);
const error = ref<unknown>(null);

async function submit() {
    if (!identifier.value.trim()) return;
    error.value = null;
    submitting.value = true;
    try {
        await requestPasswordReset({ identifier: identifier.value.trim() });
        completed.value = true;
    } catch (caught) {
        error.value = caught;
    } finally {
        submitting.value = false;
    }
}
</script>

<template>
    <AuthShell :title="t('routes.auth.passwordReset')" :description="t('auth.resetRequestHint')">
        <Message v-if="completed" severity="success" :closable="false">{{ t('auth.checkEmail') }}</Message>
        <form v-else class="flex flex-col gap-5" @submit.prevent="submit">
            <ApiErrorMessage v-if="error" :error="error" />
            <div>
                <label for="reset-identifier" class="mb-2 block font-medium">{{ t('auth.identifier') }}</label>
                <InputText id="reset-identifier" v-model="identifier" class="w-full" autocomplete="username" required />
            </div>
            <Button type="submit" :label="t('auth.requestReset')" :loading="submitting" :disabled="!identifier.trim()" />
        </form>
        <template #footer>
            <RouterLink class="text-primary font-medium" :to="{ name: 'login' }">{{ t('auth.backToLogin') }}</RouterLink>
        </template>
    </AuthShell>
</template>
