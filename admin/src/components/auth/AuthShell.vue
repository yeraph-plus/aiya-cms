<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import FloatingConfigurator from '@/components/FloatingConfigurator.vue';
import { APP_NAME } from '@/env';
import { setLocale, type AppLocale } from '@/i18n';

defineProps<{
    title: string;
    description?: string;
}>();

const { locale, t } = useI18n();

function selectLocale(nextLocale: AppLocale) {
    setLocale(nextLocale);
}
</script>

<template>
    <FloatingConfigurator />
    <main class="bg-surface-50 dark:bg-surface-950 flex min-h-screen min-w-full items-center justify-center overflow-hidden px-4 py-10">
        <div class="w-full max-w-xl">
            <div class="mb-4 flex justify-end gap-2" :aria-label="t('common.language')">
                <button
                    v-for="option in [
                        ['zh-CN', t('common.chinese')],
                        ['en-US', t('common.english')]
                    ] as const"
                    :key="option[0]"
                    type="button"
                    class="rounded-full px-3 py-1.5 text-sm transition-colors"
                    :class="locale === option[0] ? 'bg-primary text-primary-contrast' : 'bg-surface-0 dark:bg-surface-900 text-muted-color hover:text-color'"
                    :aria-pressed="locale === option[0]"
                    @click="selectLocale(option[0])"
                >
                    {{ option[1] }}
                </button>
            </div>
            <div class="rounded-[3.5rem] p-[0.3rem]" style="background: linear-gradient(180deg, var(--primary-color) 10%, rgba(33, 150, 243, 0) 30%)">
                <section class="bg-surface-0 dark:bg-surface-900 rounded-[3.3rem] px-8 py-14 sm:px-14" :aria-label="title">
                    <header class="mb-8 text-center">
                        <span class="aiya-cms-mark aiya-cms-mark--large mx-auto mb-8 block shrink-0" aria-hidden="true"></span>
                        <p class="text-muted-color mb-2 text-sm font-semibold tracking-wide">
                            {{ APP_NAME }}
                        </p>
                        <h1 class="text-surface-900 dark:text-surface-0 mb-3 text-3xl font-medium">
                            {{ title }}
                        </h1>
                        <p v-if="description" class="text-muted-color m-0 leading-6">
                            {{ description }}
                        </p>
                    </header>
                    <slot />
                    <footer v-if="$slots.footer" class="mt-7 text-center text-sm text-muted-color">
                        <slot name="footer" />
                    </footer>
                </section>
            </div>
        </div>
    </main>
</template>
