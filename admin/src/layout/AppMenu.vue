<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import AppMenuItem from './AppMenuItem.vue';
import type { MenuItem } from '@/layout/composables/layout';
import { productMenu } from '@/navigation/menu';
import { filterMenu } from '@/navigation/visibility';
import { sessionCapabilities } from '@/auth/session';

const router = useRouter();

const model = computed<MenuItem[]>(() => {
    const visible = filterMenu(productMenu, {
        capabilities: sessionCapabilities.value,
        isRouteRegistered: (name) => (name ? router.hasRoute(name) : true)
    });

    if (!import.meta.env.DEV) return visible;

    return [
        ...visible,
        {
            label: 'Demo Gallery',
            icon: 'pi pi-fw pi-window-maximize',
            path: '/demo',
            items: [
                {
                    label: 'Dashboard',
                    icon: 'pi pi-fw pi-home',
                    to: '/demo/dashboard'
                },
                {
                    label: 'UI Kit',
                    icon: 'pi pi-fw pi-palette',
                    items: [
                        { label: 'Buttons', icon: 'pi pi-fw pi-bolt', to: '/demo/uikit/button' },
                        { label: 'Form Layout', icon: 'pi pi-fw pi-th-large', to: '/demo/uikit/formlayout' },
                        { label: 'Input', icon: 'pi pi-fw pi-pencil', to: '/demo/uikit/input' },
                        { label: 'Table', icon: 'pi pi-fw pi-table', to: '/demo/uikit/table' },
                        { label: 'List', icon: 'pi pi-fw pi-list', to: '/demo/uikit/list' },
                        { label: 'Tree', icon: 'pi pi-fw pi-sitemap', to: '/demo/uikit/tree' },
                        { label: 'Panel', icon: 'pi pi-fw pi-window-maximize', to: '/demo/uikit/panel' },
                        { label: 'Overlay', icon: 'pi pi-fw pi-eye', to: '/demo/uikit/overlay' },
                        { label: 'Media', icon: 'pi pi-fw pi-images', to: '/demo/uikit/media' },
                        { label: 'Message', icon: 'pi pi-fw pi-comment', to: '/demo/uikit/message' },
                        { label: 'File', icon: 'pi pi-fw pi-file', to: '/demo/uikit/file' },
                        { label: 'Menu', icon: 'pi pi-fw pi-bars', to: '/demo/uikit/menu' },
                        { label: 'Charts', icon: 'pi pi-fw pi-chart-bar', to: '/demo/uikit/charts' },
                        { label: 'Misc', icon: 'pi pi-fw pi-circle', to: '/demo/uikit/misc' },
                        { label: 'Timeline', icon: 'pi pi-fw pi-calendar', to: '/demo/uikit/timeline' }
                    ]
                },
                {
                    label: 'CRUD',
                    icon: 'pi pi-fw pi-database',
                    to: '/demo/crud'
                },
                {
                    label: 'Blocks',
                    icon: 'pi pi-fw pi-th-large',
                    to: '/demo/blocks'
                },
                {
                    label: 'Landing',
                    icon: 'pi pi-fw pi-home',
                    to: '/demo/landing'
                },
                {
                    label: 'Documentation',
                    icon: 'pi pi-fw pi-book',
                    to: '/demo/documentation'
                }
            ]
        }
    ];
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
