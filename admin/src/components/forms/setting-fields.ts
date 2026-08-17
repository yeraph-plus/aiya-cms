import type { Component } from 'vue';
import type { components } from '@/api/schema';
import FileUpload from 'primevue/fileupload';
import InputText from 'primevue/inputtext';
import MultiSelect from 'primevue/multiselect';
import RadioButton from 'primevue/radiobutton';
import Select from 'primevue/select';
import Textarea from 'primevue/textarea';
import ToggleSwitch from 'primevue/toggleswitch';

export type SettingFieldDTO = components['schemas']['SettingFieldDTO'];
export type SettingFieldType = SettingFieldDTO['type'];
export type SettingScalar = string | number | boolean | null;
export type SettingValue = SettingScalar | SettingValue[];
export type SettingValues = Record<string, SettingValue>;
export type SettingOption = { value: SettingScalar };

const fieldComponentNames: Record<SettingFieldType, string> = {
    bool: 'ToggleSwitch',
    text: 'InputText',
    textarea: 'Textarea',
    select: 'Select',
    radio: 'RadioButton',
    mult: 'MultiSelect',
    upload: 'FileUpload'
};

const fieldComponents: Record<SettingFieldType, Component> = {
    bool: ToggleSwitch,
    text: InputText,
    textarea: Textarea,
    select: Select,
    radio: RadioButton,
    mult: MultiSelect,
    upload: FileUpload
};

export function settingFieldComponentName(type: SettingFieldType): string {
    return fieldComponentNames[type];
}

export function settingFieldComponent(type: SettingFieldType): Component {
    return fieldComponents[type];
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function isSettingScalar(value: unknown): value is SettingScalar {
    return value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';
}

export function isSettingValue(value: unknown): value is SettingValue {
    if (isSettingScalar(value)) return true;
    return Array.isArray(value) && value.every((item) => isSettingValue(item));
}

export function isSettingScalarArray(value: unknown): value is SettingScalar[] {
    return Array.isArray(value) && value.every((item) => isSettingScalar(item));
}

export function settingOptions(field: SettingFieldDTO): SettingOption[] {
    const raw = field.metadata.options;
    if (raw === undefined) return [];
    if (!Array.isArray(raw)) throw new Error(`Invalid options metadata for setting field ${field.slug}`);

    return raw.map((option, index) => {
        if (!isRecord(option)) {
            throw new Error(`Invalid option ${index} for setting field ${field.slug}`);
        }
        const value = option.value;
        if (!isSettingScalar(value)) {
            throw new Error(`Invalid option ${index} for setting field ${field.slug}`);
        }
        return { value };
    });
}

export function settingRows(field: SettingFieldDTO): number | undefined {
    const value = field.metadata.rows;
    return typeof value === 'number' ? value : undefined;
}

export function settingAccept(field: SettingFieldDTO): string | undefined {
    const value = field.metadata.accept;
    if (!Array.isArray(value)) return undefined;
    const accept = value.filter((item): item is string => typeof item === 'string');
    return accept.length > 0 ? accept.join(',') : undefined;
}

export function settingMaxLength(field: SettingFieldDTO): number | undefined {
    const value = field.metadata.max_length;
    return typeof value === 'number' ? value : undefined;
}

export function settingMaxSize(field: SettingFieldDTO): number | undefined {
    const value = field.metadata.max_size;
    return typeof value === 'number' ? value : undefined;
}

export function settingIsMultiple(field: SettingFieldDTO): boolean {
    return field.type_sub === 'multiple' || field.metadata.multiple === true;
}

function cloneSettingValue(value: SettingValue): SettingValue {
    return Array.isArray(value) ? value.map(cloneSettingValue) : value;
}

export function editableSettingValues(values: Record<string, unknown>): SettingValues {
    const editable: SettingValues = {};
    for (const [slug, value] of Object.entries(values)) {
        if (!isSettingValue(value)) {
            throw new Error(`Invalid value for setting field ${slug}`);
        }
        editable[slug] = cloneSettingValue(value);
    }
    return editable;
}
