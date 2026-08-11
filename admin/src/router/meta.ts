import 'vue-router';

export interface RouteMeta {
    titleKey: string;
    requiresAuth: boolean;
    requiredCapability?: string;
    shell: 'auth' | 'app';
}

declare module 'vue-router' {
    interface RouteMeta {
        titleKey: string;
        requiresAuth: boolean;
        requiredCapability?: string;
        shell: 'auth' | 'app';
    }
}
