import { sessionCapabilities } from '@/auth/session';

export function useCapability() {
    return {
        has: (capability: string) => sessionCapabilities.value.has(capability)
    };
}
