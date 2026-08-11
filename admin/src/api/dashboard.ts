import type { components, paths } from './schema';
import { getApi } from './index';

export type AdminDashboardDTO = components['schemas']['AdminDashboardDTO'];
export type DashboardWindow = NonNullable<paths['/api/v1/admin/dashboard/summary']['get']['parameters']['query']>['window'];

export async function fetchDashboard(window: DashboardWindow = '7d', signal?: AbortSignal): Promise<AdminDashboardDTO> {
    return getApi().get('/api/v1/admin/dashboard/summary', { window }, signal);
}
