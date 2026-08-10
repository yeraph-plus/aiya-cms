export interface PageDTO<T> {
    items: T[];
    page: number;
    size: number;
    total: number;
}

export function pageQuery(page: number, size: number): Record<string, number> {
    return { page, size };
}

export function pageCount(total: number, size: number): number {
    return size > 0 ? Math.ceil(total / size) : 0;
}

export function isPageDTO<T>(value: unknown): value is PageDTO<T> {
    return (
        typeof value === 'object' && value !== null && Array.isArray((value as PageDTO<T>).items) && typeof (value as PageDTO<T>).page === 'number' && typeof (value as PageDTO<T>).size === 'number' && typeof (value as PageDTO<T>).total === 'number'
    );
}
