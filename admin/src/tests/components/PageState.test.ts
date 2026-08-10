import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import PageState from '@/components/feedback/PageState.vue';
import { ApiError } from '@/api/errors';

const stubs = { Skeleton: true, Message: { template: '<div class="message"><slot /></div>' } };

describe('PageState', () => {
    it('renders skeletons while loading', () => {
        const wrapper = mount(PageState, { props: { state: 'loading' }, global: { stubs } });
        expect(wrapper.findAllComponents({ name: 'Skeleton' }).length).toBeGreaterThan(0);
    });

    it('renders the safe error message', () => {
        const error = new ApiError(422, { detail: 'invalid input' });
        const wrapper = mount(PageState, { props: { state: 'error', error }, global: { stubs } });
        expect(wrapper.text()).toContain('invalid input');
    });

    it('renders empty state with title and description', () => {
        const wrapper = mount(PageState, { props: { state: 'empty', title: 'No users', description: 'Try another filter' }, global: { stubs } });
        expect(wrapper.text()).toContain('No users');
        expect(wrapper.text()).toContain('Try another filter');
    });

    it('renders the default slot in ready state', () => {
        const wrapper = mount(PageState, { props: { state: 'ready' }, slots: { default: '<div class="content">ready</div>' } });
        expect(wrapper.find('.content').exists()).toBe(true);
    });
});
