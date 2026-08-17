<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import type { FileUploadUploaderEvent } from 'primevue/fileupload';
import type { SettingFieldDTO } from '@/api/settings';
import { isSettingScalar, isSettingScalarArray, settingAccept, settingFieldComponent, settingIsMultiple, settingMaxLength, settingMaxSize, settingOptions, settingRows, type SettingValue } from './setting-fields';

const { t, te } = useI18n();
const props = withDefaults(
    defineProps<{
        field: SettingFieldDTO;
        groupKey: string;
        modelValue?: SettingValue;
        sensitiveConfigured?: boolean;
        disabled?: boolean;
        uploadAsset?: (file: File) => Promise<string>;
    }>(),
    { disabled: false, sensitiveConfigured: false }
);

const emit = defineEmits<{
    'update:modelValue': [value: SettingValue];
    'upload-error': [error: Error];
    'clear-sensitive': [];
}>();

const fieldComponent = computed(() => settingFieldComponent(props.field.type));
const textKey = (suffix: string) => `settings.fields.${props.groupKey}.${props.field.slug}.${suffix}`;
const optionKey = (value: SettingValue) => `settings.fields.${props.groupKey}.${props.field.slug}.options[${JSON.stringify(String(value))}]`;
const localized = (key: string) => (te(key) ? t(key) : key);
const fieldLabel = computed(() => localized(textKey('label')));
const fieldDescription = computed(() => {
    const key = textKey('description');
    return te(key) ? t(key) : '';
});
const placeholder = computed(() => {
    const key = textKey('placeholder');
    return te(key) ? t(key) : undefined;
});
const options = computed(() =>
    settingOptions(props.field).map((option) => ({
        ...option,
        label: localized(optionKey(option.value))
    }))
);
const uploading = ref(false);

const componentValue = computed<SettingValue>({
    get() {
        switch (props.field.type) {
            case 'bool':
                return props.modelValue === true;
            case 'text':
            case 'textarea':
                if (props.modelValue === undefined) return '';
                return props.modelValue === null || typeof props.modelValue === 'string' ? props.modelValue : String(props.modelValue);
            case 'select':
            case 'radio':
                return isSettingScalar(props.modelValue) ? props.modelValue : null;
            case 'mult':
                return isSettingScalarArray(props.modelValue) ? props.modelValue : [];
            case 'upload':
                return props.modelValue ?? null;
            default:
                throw new Error(`Unsupported setting field type: ${String(props.field.type)}`);
        }
    },
    set(value) {
        emit('update:modelValue', value);
    }
});

const componentProps = computed<Record<string, boolean | number | string | undefined | object>>(() => {
    switch (props.field.type) {
        case 'text':
            return {
                id: props.field.slug,
                type: props.field.type_sub === 'password' ? 'password' : 'text',
                placeholder: placeholder.value,
                maxlength: settingMaxLength(props.field),
                fluid: true
            };
        case 'textarea':
            return {
                id: props.field.slug,
                rows: settingRows(props.field),
                placeholder: placeholder.value,
                maxlength: settingMaxLength(props.field),
                autoResize: true,
                fluid: true
            };
        case 'select':
            return {
                inputId: props.field.slug,
                options: options.value,
                optionLabel: 'label',
                optionValue: 'value',
                placeholder: placeholder.value,
                fluid: true
            };
        case 'mult':
            return {
                inputId: props.field.slug,
                options: options.value,
                optionLabel: 'label',
                optionValue: 'value',
                placeholder: placeholder.value,
                fluid: true
            };
        default:
            return {};
    }
});

function assetFiles(event: FileUploadUploaderEvent): File[] {
    return Array.isArray(event.files) ? event.files : [event.files];
}

function asError(error: unknown): Error {
    return error instanceof Error ? error : new Error('资产上传失败，请稍后重试');
}

async function upload(event: FileUploadUploaderEvent): Promise<void> {
    if (!props.uploadAsset) {
        emit('upload-error', new Error('当前页面未绑定资产上传流程'));
        return;
    }

    const files = settingIsMultiple(props.field) ? assetFiles(event) : assetFiles(event).slice(0, 1);
    if (files.length === 0) return;

    uploading.value = true;
    try {
        const assetIds: string[] = [];
        for (const file of files) assetIds.push(await props.uploadAsset(file));
        emit('update:modelValue', settingIsMultiple(props.field) ? assetIds : assetIds[0]);
    } catch (error) {
        emit('upload-error', asError(error));
    } finally {
        uploading.value = false;
    }
}
</script>

<template>
    <div class="flex flex-col gap-2">
        <label :for="field.slug" class="font-medium text-surface-900 dark:text-surface-0">{{ fieldLabel }}</label>
        <small v-if="fieldDescription" class="text-muted-color">{{ fieldDescription }}</small>
        <div v-if="field.sensitive" class="flex items-center gap-2 text-sm text-muted-color">
            <span>{{ sensitiveConfigured ? '已配置；留空保存将保留现值' : '尚未配置' }}</span>
            <Button v-if="sensitiveConfigured" :label="t('common.clear')" severity="danger" text size="small" :disabled="disabled" @click="emit('clear-sensitive')" />
        </div>

        <component :is="fieldComponent" v-if="field.type !== 'radio' && field.type !== 'upload'" v-model="componentValue" v-bind="componentProps" :disabled="disabled" />

        <div v-else-if="field.type === 'radio'" class="flex flex-wrap gap-4">
            <div v-for="option in options" :key="`${field.slug}-${String(option.value)}`" class="flex items-center gap-2">
                <component :is="fieldComponent" v-model="componentValue" :input-id="`${field.slug}-${String(option.value)}`" :name="field.slug" :value="option.value" :disabled="disabled" />
                <label :for="`${field.slug}-${String(option.value)}`">{{ option.label }}</label>
            </div>
        </div>

        <div v-else class="flex flex-col gap-2">
            <component :is="fieldComponent" :accept="settingAccept(field)" :max-file-size="settingMaxSize(field)" :multiple="settingIsMultiple(field)" :custom-upload="true" :disabled="disabled || uploading" @uploader="upload" />
            <span v-if="typeof modelValue === 'string' && modelValue" class="text-sm text-muted-color">当前资产 ID：{{ modelValue }}</span>
            <span v-else-if="Array.isArray(modelValue) && modelValue.length" class="text-sm text-muted-color">已选择 {{ modelValue.length }} 个资产</span>
            <small v-if="uploading" class="text-muted-color">{{ t('workbenches.settings.uploading') }}</small>
        </div>
    </div>
</template>
