const exactPaths = new Set(['/api/v1/site']);
const allowedPrefixes = [
    '/api/v1/auth',
    '/api/v1/me',
    '/api/v1/posts',
    '/api/v1/pages',
    '/api/v1/community/discussions',
    '/api/v1/community/tags'
];

export function assertUserApiPath(path: string): string {
    const pathname = new URL(path, 'https://api.invalid').pathname;
    const allowed =
        exactPaths.has(pathname) ||
        allowedPrefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
    if (!allowed) throw new Error(`${pathname} is not part of the user API projection`);
    return path;
}
