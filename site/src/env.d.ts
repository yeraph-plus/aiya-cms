/// <reference types="astro/client" />

import type { AuthSession, OidcTransaction, PublicSessionUser } from '@/lib/auth/session';
import type { Locale } from '@/lib/i18n';

declare global {
    namespace App {
        interface Locals {
            locale: Locale;
            requestId: string;
            user?: PublicSessionUser | undefined;
        }

        interface SessionData {
            auth: AuthSession;
            csrfToken: string;
            oidcTransaction: OidcTransaction;
        }
    }
}

export {};
