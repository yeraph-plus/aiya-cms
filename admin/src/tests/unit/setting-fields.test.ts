import { describe, expect, it } from 'vitest';
import type { components } from '@/api/schema';
import { editableSettingValues, settingFieldComponentName, settingOptions } from '@/components/forms/setting-fields';

type SettingField = components['schemas']['SettingFieldDTO'];

function field(type: SettingField['type'], metadata: SettingField['metadata'] = {}): SettingField {
    return {
        slug: 'field',
        type,
        type_sub: null,
        default: null,
        metadata,
        public: false,
        sensitive: false
    } as SettingField;
}

describe('setting field registry', () => {
    it('maps every backend field type to a kit component', () => {
        expect((['bool', 'text', 'textarea', 'select', 'radio', 'mult', 'upload'] as const).map(settingFieldComponentName)).toEqual(['ToggleSwitch', 'InputText', 'Textarea', 'Select', 'RadioButton', 'MultiSelect', 'FileUpload']);
    });

    it('preserves stable option values without backend display labels', () => {
        const options = settingOptions(
            field('select', {
                options: [{ value: true }, { value: 2 }, { value: 'name' }]
            })
        );

        expect(options).toEqual([{ value: true }, { value: 2 }, { value: 'name' }]);
    });

    it('copies backend values for editing without inventing missing values', () => {
        const values = { enabled: true, labels: ['one', 'two'] };
        const editable = editableSettingValues(values);

        expect(editable).toEqual(values);
        expect(editable).not.toBe(values);
        expect(editable['labels']).not.toBe(values.labels);
    });
});
