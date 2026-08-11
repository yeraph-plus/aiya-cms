<script setup lang="ts">
import { useLayout } from '@/layout/composables/layout';
import AppConfigurator from './AppConfigurator.vue';
import { APP_NAME } from '@/env';
import { useI18n } from 'vue-i18n';
import { setLocale } from '@/i18n';

const { toggleMenu, toggleDarkMode, isDarkTheme } = useLayout();
const { locale, t } = useI18n();

function toggleLocale(): void {
    setLocale(locale.value === 'zh-CN' ? 'en-US' : 'zh-CN');
}

const onSignOut = async () => {
    const { signOut } = await import('@/auth/session');
    await signOut();
};
</script>

<template>
    <div class="layout-topbar">
        <div class="layout-topbar-logo-container">
            <button class="layout-menu-button layout-topbar-action" @click="toggleMenu">
                <i class="pi pi-bars"></i>
            </button>
            <router-link to="/dashboard" class="layout-topbar-logo">
                <span class="aiya-cms-mark" aria-hidden="true"></span>
                <span>{{ APP_NAME }}</span>
            </router-link>
        </div>

        <div class="layout-topbar-actions">
            <div class="layout-config-menu">
                <button type="button" class="layout-topbar-action" :title="t('common.language')" @click="toggleLocale">
                    <i class="pi pi-language"></i>
                    <span>{{ locale === 'zh-CN' ? 'EN' : '中' }}</span>
                </button>
                <button type="button" class="layout-topbar-action" @click="toggleDarkMode">
                    <i :class="['pi', { 'pi-moon': isDarkTheme, 'pi-sun': !isDarkTheme }]" />
                </button>
                <div class="relative">
                    <button
                        v-styleclass="{ selector: '@next', enterFromClass: 'hidden', enterActiveClass: 'p-anchored-overlay-enter-active', leaveToClass: 'hidden', leaveActiveClass: 'p-anchored-overlay-leave-active', hideOnOutsideClick: true }"
                        type="button"
                        class="layout-topbar-action layout-topbar-action-highlight"
                    >
                        <i class="pi pi-palette"></i>
                    </button>
                    <AppConfigurator />
                </div>
            </div>

            <button
                class="layout-topbar-menu-button layout-topbar-action"
                v-styleclass="{ selector: '@next', enterFromClass: 'hidden', enterActiveClass: 'p-anchored-overlay-enter-active', leaveToClass: 'hidden', leaveActiveClass: 'p-anchored-overlay-leave-active', hideOnOutsideClick: true }"
            >
                <i class="pi pi-ellipsis-v"></i>
            </button>

            <div class="layout-topbar-menu hidden lg:block">
                <div class="layout-topbar-menu-content">
                    <button type="button" class="layout-topbar-action" @click="onSignOut">
                        <i class="pi pi-sign-out"></i>
                        <span>{{ t('common.signOut') }}</span>
                    </button>
                </div>
            </div>
        </div>
    </div>
</template>
