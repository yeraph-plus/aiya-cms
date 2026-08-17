<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute } from 'vue-router';
import { confirmPasswordReset } from '@/api/auth';
import AuthShell from '@/components/auth/AuthShell.vue';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';

const route = useRoute();
const { t } = useI18n();
const token = ref(typeof route.query.token === 'string' ? route.query.token : '');
const password = ref('');
const confirmPassword = ref('');
const submitting = ref(false);
const completed = ref(false);
const error = ref<unknown>(null);
const validationMessage = ref('');
const canSubmit = computed(() => Boolean(token.value.trim() && password.value.length >= 12 && confirmPassword.value.length >= 12));

async function submit() {
    validationMessage.value = '';
    if (password.value !== confirmPassword.value) {
        validationMessage.value = t('auth.passwordMismatch');
        return;
    }
    error.value = null;
    submitting.value = true;
    try {
        await confirmPasswordReset({
            token: token.value.trim(),
            new_password: password.value
        });
        completed.value = true;
    } catch (caught) {
        error.value = caught;
    } finally {
        submitting.value = false;
    }
}
</script>

<template>
    <AuthShell :title="t('routes.auth.passwordResetConfirm')" :description="t('auth.resetConfirmHint')">
        <Message v-if="completed" severity="success" :closable="false">{{ t('auth.passwordChanged') }}</Message>
        <form v-else class="flex flex-col gap-5" @submit.prevent="submit">
            <ApiErrorMessage v-if="error" :error="error" />
            <Message v-if="validationMessage" severity="warn" :closable="false">{{ validationMessage }}</Message>
            <div>
                <label for="reset-token" class="mb-2 block font-medium">{{ t('auth.resetToken') }}</label>
                <InputText id="reset-token" v-model="token" class="w-full" autocomplete="one-time-code" required />
            </div>
            <div>
                <label for="reset-new-password" class="mb-2 block font-medium">{{ t('auth.newPassword') }}</label>
                <Password id="reset-new-password" v-model="password" class="w-full" fluid :feedback="false" toggle-mask autocomplete="new-password" required />
                <small class="text-muted-color">{{ t('auth.passwordMinimum') }}</small>
            </div>
            <div>
                <label for="reset-confirm-password" class="mb-2 block font-medium">{{ t('auth.confirmPassword') }}</label>
                <Password id="reset-confirm-password" v-model="confirmPassword" class="w-full" fluid :feedback="false" toggle-mask autocomplete="new-password" required />
            </div>
            <Button type="submit" :label="t('auth.resetPassword')" :loading="submitting" :disabled="!canSubmit" />
        </form>
        <template #footer>
            <RouterLink class="text-primary font-medium" :to="{ name: 'login' }">{{ t('auth.backToLogin') }}</RouterLink>
        </template>
    </AuthShell>
</template>
