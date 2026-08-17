<script setup lang="ts">
import { Languages, MonitorCog, Moon, Sun } from 'lucide-vue-next';
import {
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuPortal,
    DropdownMenuRoot,
    DropdownMenuSeparator,
    DropdownMenuTrigger
} from 'reka-ui';
import { ref } from 'vue';

import type { Locale } from '@/lib/i18n';
import type { Theme } from '@/lib/theme';

interface Labels {
    open: string;
    language: string;
    chinese: string;
    english: string;
    theme: string;
    system: string;
    light: string;
    dark: string;
}

const props = defineProps<{
    currentLocale: Locale;
    currentTheme: Theme;
    localeLinks: { locale: Locale; href: string; label: string }[];
    labels: Labels;
}>();

const selectedTheme = ref<Theme>(props.currentTheme);

function setTheme(theme: Theme) {
    selectedTheme.value = theme;
    document.documentElement.dataset.theme = theme;
    const secure = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = `aiya-theme=${theme}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;
}

const themeOptions: { value: Theme; label: string; icon: typeof MonitorCog }[] = [
    { value: 'system', label: props.labels.system, icon: MonitorCog },
    { value: 'light', label: props.labels.light, icon: Sun },
    { value: 'dark', label: props.labels.dark, icon: Moon }
];
</script>

<template>
    <DropdownMenuRoot>
        <DropdownMenuTrigger class="icon-button" :aria-label="labels.open">
            <MonitorCog :size="18" aria-hidden="true" />
        </DropdownMenuTrigger>
        <DropdownMenuPortal>
            <DropdownMenuContent class="utility-menu" :side-offset="10" align="end">
                <DropdownMenuLabel class="utility-menu-label"
                    ><Languages :size="15" aria-hidden="true" />{{ labels.language }}</DropdownMenuLabel
                >
                <DropdownMenuItem v-for="option in localeLinks" :key="option.locale" as-child>
                    <a
                        class="utility-menu-item"
                        :class="{ selected: option.locale === currentLocale }"
                        :href="option.href"
                        :lang="option.locale"
                    >
                        {{ option.label }}
                    </a>
                </DropdownMenuItem>
                <DropdownMenuSeparator class="utility-menu-separator" />
                <DropdownMenuLabel class="utility-menu-label">{{ labels.theme }}</DropdownMenuLabel>
                <DropdownMenuItem
                    v-for="option in themeOptions"
                    :key="option.value"
                    class="utility-menu-item"
                    :class="{ selected: option.value === selectedTheme }"
                    @select="setTheme(option.value)"
                >
                    <component :is="option.icon" :size="15" aria-hidden="true" />
                    <span>{{ option.label }}</span>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenuPortal>
    </DropdownMenuRoot>
</template>
