import type { NavMenuItem } from './menu';

export interface MenuFilterContext {
    capabilities: ReadonlySet<string>;
    isRouteRegistered: (name?: string) => boolean;
}

export function filterMenu(items: NavMenuItem[], context: MenuFilterContext): NavMenuItem[] {
    const result: NavMenuItem[] = [];
    for (const item of items) {
        const visible = item.capability === undefined || context.capabilities.has(item.capability);
        if (!visible) continue;

        if (item.routeName !== undefined && !context.isRouteRegistered(item.routeName)) continue;

        if (item.items) {
            const children = filterMenu(item.items, context);
            if (children.length === 0) continue;
            result.push({ ...item, items: children });
            continue;
        }

        result.push(item);
    }
    return result;
}
