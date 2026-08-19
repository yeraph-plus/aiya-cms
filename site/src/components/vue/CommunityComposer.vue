<script setup lang="ts">
import { ref } from 'vue';

const props = defineProps<{
    locale: 'zh-CN' | 'en';
    csrf: string;
    discussionId?: string;
    discussionEdit?: boolean;
    discussionTitle?: string;
    discussionVersion?: number;
    postId?: string;
    postBody?: string | undefined;
    postVersion?: number;
}>();

const title = ref(props.discussionTitle ?? '');
const body = ref(props.postBody ?? '');
const message = ref('');
const busy = ref(false);
const isEnglish = props.locale === 'en';

async function submit(event: Event) {
    event.preventDefault();
    busy.value = true;
    message.value = '';
    const form = event.currentTarget as HTMLFormElement;
    const data = Object.fromEntries(new FormData(form).entries());
    const path = props.postId
        ? `/api/community/posts/${props.postId}`
        : props.discussionEdit
          ? `/api/community/discussions/${props.discussionId}`
        : props.discussionId
          ? `/api/community/discussions/${props.discussionId}/replies`
          : '/api/community/discussions';
    const payload = props.postId
        ? { body: String(data.body ?? ''), expected_version: Number(props.postVersion) }
        : props.discussionEdit
          ? { title: String(data.title ?? ''), expected_version: Number(props.discussionVersion) }
        : props.discussionId
          ? { body: String(data.body ?? '') }
          : { title: String(data.title ?? ''), body: String(data.body ?? ''), template_key: 'general' };
    try {
        const response = await fetch(path, {
            method: props.postId || props.discussionEdit ? 'PATCH' : 'POST',
            credentials: 'same-origin',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json',
                'X-CSRF-Token': props.csrf,
                'Idempotency-Key': crypto.randomUUID()
            },
            body: JSON.stringify(payload)
        });
        const result = await response.json().catch(() => ({}));
        if (response.status === 401 || response.status === 403) {
            message.value = result.message ?? (isEnglish ? 'This request was refused.' : '请求被拒绝。');
        } else if (!response.ok) {
            message.value = result.detail?.[0]?.msg ?? result.message ?? (isEnglish ? 'Validation failed.' : '字段校验失败。');
        } else {
            window.location.reload();
        }
    } catch {
        message.value = isEnglish ? 'The community is unavailable.' : '社区暂时不可用。';
    } finally {
        busy.value = false;
    }
}
</script>

<template>
<form class="community-form" :action="postId ? `/api/community/posts/${postId}` : discussionEdit ? `/api/community/discussions/${discussionId}` : discussionId ? `/api/community/discussions/${discussionId}/replies` : '/api/community/discussions'" method="post" @submit="submit">
    <input type="hidden" name="csrf" :value="csrf" />
    <input v-if="postId || discussionEdit" type="hidden" name="expected_version" :value="postId ? postVersion : discussionVersion" />
    <label v-if="!discussionId || discussionEdit">
        {{ isEnglish ? 'Title' : '标题' }}
        <input v-model="title" name="title" required maxlength="200" />
    </label>
    <label>
        {{ postId ? (isEnglish ? 'Edit post' : '编辑帖子') : discussionEdit ? (isEnglish ? 'Edit discussion' : '编辑讨论') : discussionId ? (isEnglish ? 'Reply' : '回复') : (isEnglish ? 'Discussion' : '讨论内容') }}
        <textarea v-model="body" name="body" required maxlength="20000" rows="4"></textarea>
    </label>
    <button type="submit" :disabled="busy">{{ isEnglish ? 'Submit' : '提交' }}</button>
    <p v-if="message" role="alert">{{ message }}</p>
</form>
</template>

<style scoped>
.community-form { display: grid; gap: 0.7rem; margin-top: 1rem; max-width: 42rem; }
.community-form label { display: grid; gap: 0.3rem; font-weight: 600; }
.community-form input, .community-form textarea { width: 100%; padding: 0.65rem; font: inherit; }
.community-form button { justify-self: start; padding: 0.6rem 1rem; }
.community-form p { margin: 0; color: #a11; }
</style>
