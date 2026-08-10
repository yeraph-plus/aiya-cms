import 'vue-router';

export interface RouteMeta {
    title: string;
    requiresAuth: boolean;
    requiredCapability?: string;
    shell: 'auth' | 'app';
}

declare module 'vue-router' {
    interface RouteMeta {
        title: string;
        requiresAuth: boolean;
        requiredCapability?: string;
        shell: 'auth' | 'app';
    }
}
