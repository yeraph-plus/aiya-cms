<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import AppMenuItem from './AppMenuItem.vue';
import type { MenuItem } from '@/layout/composables/layout';
import { productMenu } from '@/navigation/menu';
import { filterMenu } from '@/navigation/visibility';
import { sessionCapabilities } from '@/auth/session';
import { useI18n } from 'vue-i18n';
import type { NavMenuItem } from '@/navigation/menu';

const router = useRouter();
const { t } = useI18n();

function localize(items: NavMenuItem[]): MenuItem[] {
    return items.map(({ labelKey, items: children, ...item }) => ({
        ...item,
        label: t(labelKey),
        items: children ? localize(children) : undefined
    }));
}

const model = computed<MenuItem[]>(() => {
    return localize(
        filterMenu(productMenu, {
            capabilities: sessionCapabilities.value,
            isRouteRegistered: (name) => (name ? router.hasRoute(name) : true)
        })
    );
});
</script>

<template>
    <ul class="layout-menu">
        <template v-for="(item, i) in model" :key="item">
            <app-menu-item v-if="!item.separator" :item="item" :index="i"></app-menu-item>
            <li v-if="item.separator" class="menu-separator"></li>
        </template>
    </ul>
</template>
