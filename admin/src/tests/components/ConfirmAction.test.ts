import { describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';

const requireMock = vi.fn();

vi.mock('primevue/useconfirm', () => ({
    useConfirm: () => ({ require: requireMock })
}));

describe('ConfirmAction', () => {
    it('requests confirmation with message and header before emitting', async () => {
        const wrapper = mount(ConfirmAction, {
            props: { label: 'Delete', message: 'Delete this user?', header: 'Confirm Delete' },
            global: { stubs: { Button: { template: '<button><slot /></button>' }, ConfirmPopup: true } }
        });

        await wrapper.get('button').trigger('click');

        expect(requireMock).toHaveBeenCalledTimes(1);
        expect(requireMock).toHaveBeenCalledWith(expect.objectContaining({ message: 'Delete this user?', header: 'Confirm Delete' }));
    });

    it('does not emit confirmed before acceptance', () => {
        const wrapper = mount(ConfirmAction, {
            props: { label: 'Delete', message: 'Delete?' },
            global: { stubs: { Button: { template: '<button><slot /></button>' }, ConfirmPopup: true } }
        });
        expect(wrapper.emitted('confirmed')).toBeUndefined();
    });
});
