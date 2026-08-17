<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import {
    approvePost,
    archiveDiscussion,
    deletePost,
    fetchDiscussion,
    fetchDiscussions,
    fetchPosts,
    fetchTags,
    hideDiscussion,
    hidePost,
    lockDiscussion,
    publishDiscussion,
    replaceDiscussionTags,
    restoreDiscussion,
    unlockDiscussion,
    type DiscussionDTO,
    type DiscussionPageDTO,
    type PostPageDTO,
    type PostDTO,
    type TagDTO
} from '@/api/community';
import { hasCapability } from '@/auth/session';
import ApiErrorMessage from '@/components/feedback/ApiErrorMessage.vue';
import PageState from '@/components/feedback/PageState.vue';
import PagedTable from '@/components/data/PagedTable.vue';
import EntityDrawerShell from '@/components/shell/EntityDrawerShell.vue';
import PageShell from '@/components/shell/PageShell.vue';
import SurfaceCard from '@/components/shell/SurfaceCard.vue';

const { t, locale } = useI18n();
const statuses = ['draft', 'pending', 'published', 'hidden', 'archived'];
const filters = reactive({ status: null as string | null });
const result = ref<DiscussionPageDTO | null>(null);
const selected = ref<DiscussionDTO | null>(null);
const posts = ref<PostPageDTO | null>(null);
const postPage = ref(1);
const postSize = ref(20);
const loading = ref(false);
const detailLoading = ref(false);
const actionLoading = ref(false);
const error = ref<unknown>(null);
const actionError = ref<unknown>(null);
const drawerVisible = ref(false);
const page = ref(1);
const size = ref(20);
const canModerate = computed(() => hasCapability('community.discussions.moderate'));
const canLock = computed(() => hasCapability('community.discussions.lock'));
const canArchive = computed(() => hasCapability('community.discussions.archive'));
const canModeratePosts = computed(() => hasCapability('community.posts.moderate'));
const canManageTags = computed(() => hasCapability('community.tags.manage'));
const availableTags = ref<TagDTO[]>([]);
const selectedTagIds = ref<string[]>([]);
const tagsSaving = ref(false);

async function load(resetPage = false): Promise<void> {
    if (resetPage) page.value = 1;
    loading.value = true;
    error.value = null;
    try {
        result.value = await fetchDiscussions({
            page: page.value,
            size: size.value,
            status: filters.status || undefined
        });
    } catch (caught) {
        error.value = caught;
    } finally {
        loading.value = false;
    }
}

async function openDiscussion(item: DiscussionDTO): Promise<void> {
    drawerVisible.value = true;
    detailLoading.value = true;
    actionError.value = null;
    try {
        postPage.value = 1;
        const [discussion, stream, tags] = await Promise.all([
            fetchDiscussion(item.id),
            fetchPosts({
                discussion_id: item.id,
                page: postPage.value,
                size: postSize.value
            }),
            canManageTags.value ? fetchTags(false) : Promise.resolve([] as TagDTO[])
        ]);
        selected.value = discussion;
        posts.value = stream;
        availableTags.value = tags;
        selectedTagIds.value = discussion.tags?.map((tag) => tag.id) ?? [];
    } catch (caught) {
        actionError.value = caught;
    } finally {
        detailLoading.value = false;
    }
}

async function loadPosts(targetPage: number): Promise<void> {
    if (!selected.value) return;
    actionError.value = null;
    try {
        posts.value = await fetchPosts({
            discussion_id: selected.value.id,
            page: targetPage,
            size: postSize.value
        });
        postPage.value = targetPage;
    } catch (caught) {
        actionError.value = caught;
    }
}

async function saveTags(): Promise<void> {
    if (!selected.value || !canManageTags.value) return;
    tagsSaving.value = true;
    actionError.value = null;
    try {
        replace(
            await replaceDiscussionTags(selected.value.id, {
                expected_version: selected.value.version,
                tag_ids: selectedTagIds.value
            })
        );
    } catch (caught) {
        actionError.value = caught;
    } finally {
        tagsSaving.value = false;
    }
}

function replace(item: DiscussionDTO): void {
    selected.value = item;
    if (result.value) {
        result.value = {
            ...result.value,
            items: result.value.items.map((current) => (current.id === item.id ? item : current))
        };
    }
}

async function runAction(action: (id: string) => Promise<DiscussionDTO>): Promise<void> {
    if (!selected.value) return;
    actionLoading.value = true;
    actionError.value = null;
    try {
        replace(await action(selected.value.id));
        await load();
    } catch (caught) {
        actionError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

async function runPostAction(post: PostDTO, action: (id: string) => Promise<PostDTO>): Promise<void> {
    actionLoading.value = true;
    actionError.value = null;
    try {
        const updated = await action(post.id);
        if (posts.value)
            posts.value = {
                ...posts.value,
                items: posts.value.items.map((item) => (item.id === updated.id ? updated : item))
            };
    } catch (caught) {
        actionError.value = caught;
    } finally {
        actionLoading.value = false;
    }
}

function formatDate(value: string | null | undefined): string {
    return value
        ? new Intl.DateTimeFormat(locale.value, {
              dateStyle: 'medium',
              timeStyle: 'short'
          }).format(new Date(value))
        : '-';
}

function tagNames(item: DiscussionDTO): string {
    return item.tags?.map((tag) => tag.name).join(', ') || '-';
}

function onPage(value: number): void {
    page.value = value;
    void load();
}

function onSize(value: number): void {
    size.value = value;
    page.value = 1;
    void load();
}

onMounted(() => void load());
</script>

<template>
    <PageShell :title="t('routes.community.discussions')" :description="t('workbenches.community.discussions.description')" :loading="loading" @refresh="load()">
        <SurfaceCard>
            <FilterBar :label="t('workbenches.search')" @submit="load(true)">
                <Select v-model="filters.status" :options="statuses" show-clear :placeholder="t('workbenches.status')" class="min-w-44" />
            </FilterBar>
        </SurfaceCard>

        <PageState v-if="loading && !result" state="loading" />
        <PageState v-else-if="error" state="error" :error="error" />
        <PageState v-else-if="result?.total === 0" state="empty" :title="t('workbenches.community.discussions.empty')" />
        <SurfaceCard v-else-if="result">
            <PagedTable :value="result.items" :total-records="result.total" :page="result.page" :size="result.size" :loading="loading" @update:page="onPage" @update:size="onSize">
                <Column field="title" :header="t('workbenches.community.discussions.title')" />
                <Column field="template_key" :header="t('workbenches.community.discussions.template')" />
                <Column field="status" :header="t('workbenches.status')"
                    ><template #body="{ data }"><StatusTag :value="data.status" /></template
                ></Column>
                <Column :header="t('workbenches.community.discussions.tags')"
                    ><template #body="{ data }">{{ tagNames(data) }}</template></Column
                >
                <Column field="reply_count" :header="t('workbenches.community.discussions.replies')" />
                <Column :header="t('workbenches.community.discussions.lastPosted')"
                    ><template #body="{ data }">{{ formatDate(data.last_posted_at) }}</template></Column
                >
                <Column
                    ><template #body="{ data }"><Button :label="t('workbenches.view')" text @click="openDiscussion(data)" /></template
                ></Column>
            </PagedTable>
        </SurfaceCard>

        <EntityDrawerShell v-model="drawerVisible" :title="t('workbenches.community.discussions.detail')" :description="selected?.id || ''">
            <PageState v-if="detailLoading" state="loading" />
            <ApiErrorMessage v-if="actionError" :error="actionError" />
            <div v-if="selected && !detailLoading" class="flex flex-col gap-5">
                <SurfaceCard>
                    <dl class="grid grid-cols-[9rem_1fr] gap-3 text-sm">
                        <dt class="text-muted-color">
                            {{ t('workbenches.community.discussions.title') }}
                        </dt>
                        <dd>{{ selected.title }}</dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.community.discussions.author') }}
                        </dt>
                        <dd>{{ selected.author?.display_name || selected.author_id }}</dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.community.discussions.template') }}
                        </dt>
                        <dd>{{ selected.template_key }}</dd>
                        <dt class="text-muted-color">{{ t('workbenches.status') }}</dt>
                        <dd><StatusTag :value="selected.status" /></dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.community.discussions.tags') }}
                        </dt>
                        <dd>
                            <div v-if="canManageTags" class="flex flex-wrap items-center gap-2">
                                <MultiSelect v-model="selectedTagIds" :options="availableTags" option-label="name" option-value="id" display="chip" class="min-w-64" />
                                <Button size="small" :label="t('workbenches.community.discussions.saveTags')" :loading="tagsSaving" @click="saveTags" />
                            </div>
                            <span v-else>{{ tagNames(selected) }}</span>
                        </dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.community.discussions.replies') }}
                        </dt>
                        <dd>{{ selected.reply_count }}</dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.community.discussions.lastPosted') }}
                        </dt>
                        <dd>{{ formatDate(selected.last_posted_at) }}</dd>
                        <dt class="text-muted-color">
                            {{ t('workbenches.community.discussions.locked') }}
                        </dt>
                        <dd>{{ selected.is_locked ? t('common.yes') : t('common.no') }}</dd>
                    </dl>
                </SurfaceCard>
                <SurfaceCard :title="t('workbenches.community.discussions.posts')">
                    <PageState v-if="!posts || posts.total === 0" state="empty" :title="t('workbenches.community.discussions.noPosts')" />
                    <div v-else class="flex flex-col gap-3">
                        <article v-for="post in posts.items" :key="post.id" class="rounded-border border border-surface p-3">
                            <div class="mb-2 flex items-center justify-between text-sm text-muted-color">
                                <span>#{{ post.number }} · <StatusTag :value="post.status" /> · {{ post.author?.display_name || post.author_id }}</span
                                ><span>{{ formatDate(post.created_at) }}</span>
                            </div>
                            <p class="whitespace-pre-wrap break-words">
                                {{ post.body || '-' }}
                            </p>
                            <div v-if="canModeratePosts" class="mt-3 flex flex-wrap gap-2">
                                <Button v-if="post.status === 'pending'" size="small" :label="t('workbenches.community.discussions.approvePost')" @click="runPostAction(post, approvePost)" />
                                <Button v-if="post.status === 'published'" size="small" severity="warn" :label="t('workbenches.community.discussions.hidePost')" @click="runPostAction(post, hidePost)" />
                                <Button v-if="post.status !== 'deleted'" size="small" severity="danger" text :label="t('workbenches.community.discussions.deletePost')" @click="runPostAction(post, deletePost)" />
                            </div>
                        </article>
                        <div v-if="posts.total > posts.size" class="flex items-center justify-between gap-2">
                            <Button text size="small" icon="pi pi-angle-left" :label="t('workbenches.community.discussions.previousPosts')" :disabled="postPage <= 1 || detailLoading" @click="loadPosts(postPage - 1)" />
                            <span class="text-sm text-muted-color">{{ postPage }} / {{ Math.ceil(posts.total / posts.size) }}</span>
                            <Button
                                text
                                size="small"
                                icon="pi pi-angle-right"
                                icon-pos="right"
                                :label="t('workbenches.community.discussions.nextPosts')"
                                :disabled="postPage >= Math.ceil(posts.total / posts.size) || detailLoading"
                                @click="loadPosts(postPage + 1)"
                            />
                        </div>
                    </div>
                </SurfaceCard>
                <div class="flex flex-wrap gap-2">
                    <Button v-if="canModerate && selected.status === 'pending'" :label="t('workbenches.community.discussions.publish')" :loading="actionLoading" @click="runAction(publishDiscussion)" />
                    <Button v-if="canModerate && selected.status === 'published'" :label="t('workbenches.community.discussions.hide')" severity="warn" :loading="actionLoading" @click="runAction(hideDiscussion)" />
                    <Button v-if="canModerate && selected.status === 'hidden'" :label="t('workbenches.community.discussions.restore')" :loading="actionLoading" @click="runAction(restoreDiscussion)" />
                    <Button v-if="canArchive && ['published', 'hidden'].includes(selected.status)" :label="t('workbenches.community.discussions.archive')" severity="danger" :loading="actionLoading" @click="runAction(archiveDiscussion)" />
                    <Button v-if="canLock && !selected.is_locked" :label="t('workbenches.community.discussions.lock')" severity="secondary" :loading="actionLoading" @click="runAction(lockDiscussion)" />
                    <Button v-if="canLock && selected.is_locked" :label="t('workbenches.community.discussions.unlock')" severity="secondary" :loading="actionLoading" @click="runAction(unlockDiscussion)" />
                </div>
            </div>
        </EntityDrawerShell>
    </PageShell>
</template>
