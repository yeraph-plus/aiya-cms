import type { ContentKind } from '@/lib/seo/content';

export type JsonLdObject = Record<string, unknown>;
export type JsonLd = JsonLdObject | readonly JsonLdObject[];

export interface SeoInput {
    title: string;
    description?: string;
    siteName?: string;
    siteOrigin: string | URL;
    canonical?: string | URL | undefined;
    noindex?: boolean;
    nofollow?: boolean | undefined;
    ogType?: 'article' | 'website' | undefined;
    ogImage?: string | URL | undefined;
}

export interface SeoMetadata {
    title: string;
    description: string;
    canonical: string;
    robots: string;
    openGraph: {
        title: string;
        description: string;
        type: 'article' | 'website';
        url: string;
        siteName?: string;
        image?: string;
    };
}

function cleanText(value: string | null | undefined): string {
    return (value ?? '').replace(/\s+/gu, ' ').trim();
}

export function truncateText(value: string | null | undefined, length = 160): string {
    const text = cleanText(value);
    if (Array.from(text).length <= length) return text;
    return `${Array.from(text)
        .slice(0, Math.max(1, length - 1))
        .join('')}…`;
}

export function absoluteSiteUrl(value: string | URL, siteOrigin: string | URL): string {
    const origin = new URL(siteOrigin.toString());
    const candidate = new URL(value.toString(), origin);
    if (candidate.origin !== origin.origin) return origin.href;
    candidate.search = '';
    candidate.hash = '';
    return candidate.href;
}

function safeImageUrl(value: string | URL | undefined, siteOrigin: string | URL): string | undefined {
    if (!value) return undefined;
    try {
        const image = new URL(value.toString(), new URL(siteOrigin.toString()));
        if (image.protocol !== 'http:' && image.protocol !== 'https:') return undefined;
        return image.href;
    } catch {
        return undefined;
    }
}

export function buildSeoMetadata(input: SeoInput): SeoMetadata {
    const siteName = cleanText(input.siteName);
    const pageTitle = cleanText(input.title) || siteName;
    const title = siteName && pageTitle !== siteName ? `${pageTitle} · ${siteName}` : pageTitle;
    const description = truncateText(input.description, 180);
    const noindex = input.noindex ?? true;
    const nofollow = input.nofollow ?? noindex;
    const canonical = absoluteSiteUrl(input.canonical ?? '/', input.siteOrigin);
    const image = safeImageUrl(input.ogImage, input.siteOrigin);

    return {
        title,
        description,
        canonical,
        robots: `${noindex ? 'noindex' : 'index'}, ${nofollow ? 'nofollow' : 'follow'}`,
        openGraph: {
            title: pageTitle,
            description,
            type: input.ogType ?? 'website',
            url: canonical,
            ...(siteName ? { siteName } : {}),
            ...(image ? { image } : {})
        }
    };
}

export function buildContentJsonLd(input: {
    kind: ContentKind;
    title: string;
    description: string;
    canonical: string;
    publishedAt?: string;
    modifiedAt?: string;
}): JsonLdObject {
    const type = input.kind === 'post' ? 'Article' : input.kind === 'page' ? 'WebPage' : 'CreativeWork';
    return {
        '@context': 'https://schema.org',
        '@type': type,
        headline: input.title,
        name: input.title,
        description: input.description,
        url: input.canonical,
        ...(input.publishedAt ? { datePublished: input.publishedAt } : {}),
        ...(input.modifiedAt ? { dateModified: input.modifiedAt } : {})
    };
}

export function buildCollectionJsonLd(input: { title: string; description: string; canonical: string }): JsonLdObject {
    return {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        name: input.title,
        description: input.description,
        url: input.canonical
    };
}

export function serializeJsonLd(value: JsonLd): string {
    return (JSON.stringify(value) ?? '{}')
        .replace(/</gu, '\\u003c')
        .replace(/>/gu, '\\u003e')
        .replace(/&/gu, '\\u0026')
        .replace(/\u2028/gu, '\\u2028')
        .replace(/\u2029/gu, '\\u2029');
}
