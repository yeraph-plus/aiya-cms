import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import ConfirmAction from '@/components/feedback/ConfirmAction.vue';

const global = {
    stubs: {
        Button: { props: ['label'], emits: ['click'], template: '<button data-test="trigger" @click="$emit(\'click\')">{{ label }}</button>' },
        SensitiveActionDialog: {
            props: ['modelValue', 'title', 'message', 'confirmLabel'],
            emits: ['update:modelValue', 'confirm'],
            template: '<button v-if="modelValue" data-test="confirm" :data-title="title" :data-label="confirmLabel" @click="$emit(\'confirm\')">{{ message }}</button>'
        }
    }
};

describe('ConfirmAction', () => {
    it('requests confirmation with message and header before emitting', async () => {
        const wrapper = mount(ConfirmAction, {
            props: { label: 'Delete', message: 'Delete this user?', header: 'Confirm Delete' },
            global
        });

        await wrapper.get('[data-test="trigger"]').trigger('click');

        expect(wrapper.get('[data-test="confirm"]').text()).toBe('Delete this user?');
        expect(wrapper.get('[data-test="confirm"]').attributes()).toMatchObject({ 'data-title': 'Confirm Delete', 'data-label': 'Delete' });
    });

    it('does not emit confirmed before acceptance', () => {
        const wrapper = mount(ConfirmAction, {
            props: { label: 'Delete', message: 'Delete?' },
            global
        });
        expect(wrapper.emitted('confirmed')).toBeUndefined();
    });
});
