import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';
import { i18n } from '@/i18n';

describe('shared administrator shells', () => {
    it('combines the page title, actions and refresh affordance', async () => {
        const wrapper = mount(PageShell, {
            props: { title: 'Users', description: 'Manage users', loading: false },
            slots: { actions: '<button data-test="custom-action">Create</button>', default: '<div>content</div>' },
            global: { plugins: [i18n], stubs: { Toolbar: { template: '<div><slot name="start"/><slot name="end"/></div>' }, Button: { emits: ['click'], template: '<button data-test="refresh" @click="$emit(\'click\')">refresh</button>' } } }
        });

        expect(wrapper.text()).toContain('Users');
        expect(wrapper.text()).toContain('Manage users');
        expect(wrapper.find('[data-test="custom-action"]').exists()).toBe(true);
        await wrapper.find('[data-test="refresh"]').trigger('click');
        expect(wrapper.emitted('refresh')).toHaveLength(1);
    });

    it('provides a consistent titled surface without forcing a nested page route', () => {
        const wrapper = mount(SurfaceCard, { props: { title: 'Account' }, slots: { default: '<p>profile</p>' } });
        expect(wrapper.text()).toContain('Account');
        expect(wrapper.text()).toContain('profile');
    });
});
