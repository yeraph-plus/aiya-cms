import { ref, shallowRef } from 'vue';

export function useAsyncState<T>(initial?: T) {
    const data = shallowRef<T | undefined>(initial);
    const loading = ref(false);
    const error = ref<unknown>(null);

    const run = async (task: () => Promise<T>): Promise<T | undefined> => {
        loading.value = true;
        error.value = null;
        try {
            const result = await task();
            data.value = result;
            return result;
        } catch (caught) {
            error.value = caught;
            return undefined;
        } finally {
            loading.value = false;
        }
    };

    return { data, loading, error, run };
}
