import type { RouteRecordRaw } from 'vue-router';
import AppLayout from '@/layout/AppLayout.vue';

const demoAppMeta = { requiresAuth: true, shell: 'app' as const };

export const demoRoutes: RouteRecordRaw[] = [
    {
        path: '/demo',
        component: AppLayout,
        children: [
            {
                path: 'dashboard',
                name: 'demo-dashboard',
                component: () => import('@/demo/pages/Dashboard.vue'),
                meta: { title: 'Demo Dashboard', ...demoAppMeta }
            },
            {
                path: 'crud',
                name: 'demo-crud',
                component: () => import('@/demo/pages/Crud.vue'),
                meta: { title: 'Demo CRUD', ...demoAppMeta }
            },
            {
                path: 'documentation',
                name: 'demo-documentation',
                component: () => import('@/demo/pages/Documentation.vue'),
                meta: { title: 'Documentation', ...demoAppMeta }
            },
            {
                path: 'blocks',
                name: 'demo-blocks',
                component: () => import('@/demo/pages/Blocks.vue'),
                meta: { title: 'Blocks', ...demoAppMeta }
            },
            {
                path: 'uikit/formlayout',
                name: 'demo-formlayout',
                component: () => import('@/demo/pages/uikit/FormLayout.vue'),
                meta: { title: 'Form Layout', ...demoAppMeta }
            },
            {
                path: 'uikit/input',
                name: 'demo-input',
                component: () => import('@/demo/pages/uikit/InputDoc.vue'),
                meta: { title: 'Input', ...demoAppMeta }
            },
            {
                path: 'uikit/button',
                name: 'demo-button',
                component: () => import('@/demo/pages/uikit/ButtonDoc.vue'),
                meta: { title: 'Button', ...demoAppMeta }
            },
            {
                path: 'uikit/table',
                name: 'demo-table',
                component: () => import('@/demo/pages/uikit/TableDoc.vue'),
                meta: { title: 'Table', ...demoAppMeta }
            },
            {
                path: 'uikit/list',
                name: 'demo-list',
                component: () => import('@/demo/pages/uikit/ListDoc.vue'),
                meta: { title: 'List', ...demoAppMeta }
            },
            {
                path: 'uikit/tree',
                name: 'demo-tree',
                component: () => import('@/demo/pages/uikit/TreeDoc.vue'),
                meta: { title: 'Tree', ...demoAppMeta }
            },
            {
                path: 'uikit/panel',
                name: 'demo-panel',
                component: () => import('@/demo/pages/uikit/PanelsDoc.vue'),
                meta: { title: 'Panel', ...demoAppMeta }
            },
            {
                path: 'uikit/overlay',
                name: 'demo-overlay',
                component: () => import('@/demo/pages/uikit/OverlayDoc.vue'),
                meta: { title: 'Overlay', ...demoAppMeta }
            },
            {
                path: 'uikit/media',
                name: 'demo-media',
                component: () => import('@/demo/pages/uikit/MediaDoc.vue'),
                meta: { title: 'Media', ...demoAppMeta }
            },
            {
                path: 'uikit/message',
                name: 'demo-message',
                component: () => import('@/demo/pages/uikit/MessagesDoc.vue'),
                meta: { title: 'Message', ...demoAppMeta }
            },
            {
                path: 'uikit/file',
                name: 'demo-file',
                component: () => import('@/demo/pages/uikit/FileDoc.vue'),
                meta: { title: 'File', ...demoAppMeta }
            },
            {
                path: 'uikit/menu',
                name: 'demo-menu',
                component: () => import('@/demo/pages/uikit/MenuDoc.vue'),
                meta: { title: 'Menu', ...demoAppMeta }
            },
            {
                path: 'uikit/charts',
                name: 'demo-charts',
                component: () => import('@/demo/pages/uikit/ChartDoc.vue'),
                meta: { title: 'Charts', ...demoAppMeta }
            },
            {
                path: 'uikit/misc',
                name: 'demo-misc',
                component: () => import('@/demo/pages/uikit/MiscDoc.vue'),
                meta: { title: 'Misc', ...demoAppMeta }
            },
            {
                path: 'uikit/timeline',
                name: 'demo-timeline',
                component: () => import('@/demo/pages/uikit/TimelineDoc.vue'),
                meta: { title: 'Timeline', ...demoAppMeta }
            }
        ]
    },
    {
        path: '/demo/landing',
        name: 'demo-landing',
        component: () => import('@/demo/pages/Landing.vue'),
        meta: { title: 'Landing', requiresAuth: false, shell: 'auth' }
    }
];
