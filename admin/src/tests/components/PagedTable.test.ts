import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import PagedTable from '@/components/data/PagedTable.vue';

const stubs = {
    DataTable: {
        emits: ['page'],
        template: '<button type="button" @click="$emit(\'page\', event)">page</button>',
        props: { event: { type: Object, required: true } }
    },
    EmptyTable: true
};

describe('PagedTable', () => {
    it('emits only the changed pagination dimension', async () => {
        const wrapper = mount(PagedTable, {
            props: { value: [], page: 2, size: 10 },
            global: { stubs },
            attrs: { event: { page: 1, rows: 25 } }
        });

        await wrapper.get('button').trigger('click');

        expect(wrapper.emitted('update:page')).toBeUndefined();
        expect(wrapper.emitted('update:size')).toEqual([[25]]);
    });

    it('does not emit when the DataTable repeats the current page and size', async () => {
        const wrapper = mount(PagedTable, {
            props: { value: [], page: 1, size: 10 },
            global: { stubs },
            attrs: { event: { page: 0, rows: 10 } }
        });

        await wrapper.get('button').trigger('click');

        expect(wrapper.emitted('update:page')).toBeUndefined();
        expect(wrapper.emitted('update:size')).toBeUndefined();
    });
});
