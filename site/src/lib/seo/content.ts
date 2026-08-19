import createClient from 'openapi-fetch';

import type { components, paths } from '@/lib/api/generated/schema';
import { markdownToText } from '@/lib/markdown';
import type { Locale } from '@/lib/i18n';
import { loadServerConfig } from '@/lib/config/server';
import { truncateText } from '@/lib/seo';

export type ContentKind = 'post' | 'page' | 'work';
export const contentKinds = ['post', 'page', 'work'] as const satisfies readonly ContentKind[];

type ContentDTO = components['schemas']['ContentDTO'];

export interface PublicContent {
    id: string;
    kind: ContentKind;
    slug: string;
    title: string;
    excerpt: string;
    body: string;
    bodyFormat: string;
    status: string;
    publishedAt?: string;
    updatedAt?: string;
    createdAt?: string;
    data: Record<string, unknown>;
    indexable: boolean;
}

export interface PublicContentListResult {
    ok: boolean;
    items: PublicContent[];
    page: number;
    size: number;
    total: number;
}

export interface PublicContentDetailResult {
    ok: boolean;
    content?: PublicContent | undefined;
}

const contentPaths: Record<ContentKind, string> = {
    post: '/posts',
    page: '/pages',
    work: '/works'
};

const copy = {
    'zh-CN': {
        post: {
            label: '文章',
            listTitle: '公开文章',
            listDescription: '按时间浏览公开文章。',
            empty: '暂无公开文章。',
            unavailable: '文章暂时不可用，请稍后重试。',
            notFound: '文章不存在，或已经不再公开。'
        },
        page: {
            label: '页面',
            listTitle: '文档页面',
            listDescription: '阅读公开文档与说明。',
            empty: '暂无公开页面。',
            unavailable: '页面暂时不可用，请稍后重试。',
            notFound: '页面不存在，或已经不再公开。'
        },
        work: {
            label: '作品',
            listTitle: '公开作品',
            listDescription: '浏览公开作品与创作文章。',
            empty: '暂无公开作品。',
            unavailable: '作品暂时不可用，请稍后重试。',
            notFound: '作品不存在，或已经不再公开。'
        }
    },
    en: {
        post: {
            label: 'Post',
            listTitle: 'Public posts',
            listDescription: 'Browse public posts in publishing order.',
            empty: 'No public posts yet.',
            unavailable: 'Posts are temporarily unavailable. Try again later.',
            notFound: 'This post does not exist or is no longer public.'
        },
        page: {
            label: 'Page',
            listTitle: 'Documentation',
            listDescription: 'Read public documentation and reference pages.',
            empty: 'No public pages yet.',
            unavailable: 'Pages are temporarily unavailable. Try again later.',
            notFound: 'This page does not exist or is no longer public.'
        },
        work: {
            label: 'Work',
            listTitle: 'Public works',
            listDescription: 'Browse public works and creative writing.',
            empty: 'No public works yet.',
            unavailable: 'Works are temporarily unavailable. Try again later.',
            notFound: 'This work does not exist or is no longer public.'
        }
    }
} as const;

const metadataLabels = {
    'zh-CN': {
        category: '分类',
        source: '来源',
        creator: '创作者',
        group: '组',
        character: '角色',
        language: '语言',
        genre: '类型',
        format: '格式',
        tags: '标签',
        file_count: '文件数',
        part_count: '分卷数',
        size_bytes: '大小'
    },
    en: {
        category: 'Category',
        source: 'Source',
        creator: 'Creator',
        group: 'Group',
        character: 'Character',
        language: 'Language',
        genre: 'Genre',
        format: 'Format',
        tags: 'Tags',
        file_count: 'Files',
        part_count: 'Parts',
        size_bytes: 'Size'
    }
} as const;

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(value: unknown): string | undefined {
    return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function readDate(value: unknown): string | undefined {
    const text = readString(value);
    if (!text) return undefined;
    const date = new Date(text);
    return Number.isNaN(date.valueOf()) ? undefined : date.toISOString();
}

function readNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function normalizePublicContent(value: unknown, requestedKind?: ContentKind): PublicContent | null {
    if (!isRecord(value)) return null;

    const kind = readString(value.type_name);
    const id = readString(value.id);
    const slug = readString(value.slug);
    const title = readString(value.title);
    if (!kind || !contentKinds.includes(kind as ContentKind) || (requestedKind && kind !== requestedKind)) return null;
    if (!id || !slug || !title) return null;

    const status = readString(value.status)?.toLowerCase() ?? 'unknown';
    const publishedAt = readDate(value.published_at) ?? readDate(value.publish_at);
    const updatedAt = readDate(value.updated_at);
    const createdAt = readDate(value.created_at);
    const data = isRecord(value.data) ? value.data : {};
    const archived = Boolean(readDate(value.archived_at));

    return {
        id,
        kind: kind as ContentKind,
        slug,
        title,
        excerpt: readString(value.excerpt) ?? '',
        body: readString(value.body) ?? '',
        bodyFormat: readString(value.body_format)?.toLowerCase() ?? 'markdown',
        status,
        ...(publishedAt ? { publishedAt } : {}),
        ...(updatedAt ? { updatedAt } : {}),
        ...(createdAt ? { createdAt } : {}),
        data,
        indexable: status === 'published' && !archived
    };
}

function createPublicContentClient(requestId: string) {
    const { apiOrigin } = loadServerConfig();
    const requestFetch: typeof fetch = async (input, init) => {
        const request = new Request(input, init);
        const headers = new Headers(request.headers);
        headers.set('Accept', 'application/json');
        headers.set('X-Request-ID', requestId);
        return fetch(new Request(request, { headers }));
    };

    return createClient<paths>({ baseUrl: apiOrigin, fetch: requestFetch });
}

export async function fetchPublicContentList(
    kind: ContentKind,
    requestId: string,
    options: { page?: number; size?: number; sort?: string } = {}
): Promise<PublicContentListResult> {
    const page = Math.max(1, Math.floor(options.page ?? 1));
    const size = Math.min(100, Math.max(1, Math.floor(options.size ?? 12)));
    const query: { page: number; size: number; sort?: string } = { page, size };
    if (options.sort) query.sort = options.sort;

    try {
        const response = await createPublicContentClient(requestId).GET('/api/v1/content/{type_name}', {
            params: { path: { type_name: kind }, query }
        });
        const data = response.data as components['schemas']['ContentPageDTO'] | undefined;
        if (!data || !Array.isArray(data.items)) return { ok: false, items: [], page, size, total: 0 };

        const items = data.items
            .map((item) => normalizePublicContent(item as ContentDTO, kind))
            .filter((item): item is PublicContent => item !== null && item.indexable);
        return {
            ok: true,
            items,
            page: typeof data.page === 'number' ? data.page : page,
            size: typeof data.size === 'number' ? data.size : size,
            total: typeof data.total === 'number' ? data.total : items.length
        };
    } catch {
        return { ok: false, items: [], page, size, total: 0 };
    }
}

export async function fetchPublicContentBySlug(
    kind: ContentKind,
    slug: string,
    requestId: string
): Promise<PublicContentDetailResult> {
    if (!slug) return { ok: true };
    const result = await fetchPublicContentList(kind, requestId, { page: 1, size: 100, sort: '-published_at' });
    const content = result.items.find((item) => item.slug === slug);
    return { ok: result.ok, content };
}

export function contentCollectionPath(kind: ContentKind): string {
    return contentPaths[kind];
}

export function contentDetailPath(kind: ContentKind, slug: string): string {
    return `${contentCollectionPath(kind)}/${encodeURIComponent(slug)}`;
}

export function contentCopy(kind: ContentKind, locale: Locale) {
    return copy[locale][kind];
}

export function describePublicContent(content: PublicContent): string {
    return truncateText(content.excerpt || markdownToText(content.body), 180);
}

export interface PublicContentMetadata {
    label: string;
    value: string;
}

export function publicContentMetadata(content: PublicContent, locale: Locale): PublicContentMetadata[] {
    const labels = metadataLabels[locale];
    const values: PublicContentMetadata[] = [];
    const stringKeys =
        content.kind === 'page'
            ? (['category'] as const)
            : (['category', 'source', 'creator', 'group', 'character', 'language', 'genre', 'format'] as const);
    for (const key of stringKeys) {
        const value = readString(content.data[key]);
        if (value) values.push({ label: labels[key], value: truncateText(value, 80) });
    }

    const tags =
        content.kind !== 'page' && Array.isArray(content.data.tags)
            ? content.data.tags
                  .filter((tag): tag is string => typeof tag === 'string' && tag.trim().length > 0)
                  .slice(0, 12)
            : [];
    if (tags.length) values.push({ label: labels.tags, value: tags.map((tag) => truncateText(tag, 40)).join(' · ') });

    if (content.kind === 'work') {
        for (const key of ['file_count', 'part_count', 'size_bytes'] as const) {
            const value = readNumber(content.data[key]);
            if (value !== undefined)
                values.push({ label: labels[key], value: new Intl.NumberFormat(locale).format(value) });
        }
    }
    return values;
}
