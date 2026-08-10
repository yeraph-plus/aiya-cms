import { InMemoryWebStorage, WebStorageStateStore } from 'oidc-client-ts';

export const oidcUserStorage = new WebStorageStateStore({ store: new InMemoryWebStorage() });

export const oidcStateStorage = new WebStorageStateStore({ store: window.sessionStorage });
