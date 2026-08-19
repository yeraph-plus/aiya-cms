import type { APIRoute } from 'astro';

import { accountBff } from '@/lib/user-center/bff';

export const ALL: APIRoute = accountBff;
