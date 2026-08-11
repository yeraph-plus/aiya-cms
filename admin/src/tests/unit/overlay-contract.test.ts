import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

function source(path: string): string {
    return readFileSync(new URL(path, import.meta.url), 'utf8');
}

describe('in-place entity workspaces', () => {
    it('edits list content in a drawer without restoring detail-page navigation', () => {
        const contentList = source('../../pages/content/ContentList.vue');
        expect(contentList).toContain('EntityDrawerShell');
        expect(contentList).not.toMatch(/content-editor|content-new|content-detail/);
    });

    it('uses one user workspace drawer instead of stacking independent user drawers', () => {
        const usersList = source('../../pages/identity/UsersList.vue');
        expect(usersList).toContain('UserWorkspaceDrawer');
        expect(usersList).not.toContain('<Drawer');
    });
});
