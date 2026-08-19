<script setup lang="ts">
import { ref } from 'vue';

interface Props {
    csrf: string;
    locale: 'zh-CN' | 'en';
    section: 'points' | 'membership' | 'purchases' | 'gift-card' | 'downloads';
    items?: Record<string, unknown>[];
}

const props = withDefaults(defineProps<Props>(), { items: () => [] });
const secret = ref('');
const result = ref<Record<string, unknown> | null>(null);
const responseStatus = ref<number | null>(null);
const requestId = ref<string | null>(null);
const busy = ref(false);
const payment = ref<Record<string, unknown> | null>(null);

const labels = props.locale === 'en'
    ? { checkIn: 'Check in', buy: 'Create payment order', renew: 'Renew', cancel: 'Cancel renewal', redeem: 'Redeem gift card', refresh: 'Refresh status', links: 'Get download links', provider: 'Payment provider key', reason: 'Cancellation reason', secret: 'Gift-card secret', pending: 'The browser return is not proof of payment. Refresh until the server reports a terminal state.' }
    : { checkIn: '签到', buy: '创建支付订单', renew: '续费', cancel: '取消自动续费', redeem: '兑换礼品卡', refresh: '刷新状态', links: '获取下载链接', provider: '支付渠道标识', reason: '取消原因', secret: '礼品卡卡密', pending: '浏览器回跳不代表支付成功，请刷新直到服务端返回终态。' };

function stringValue(item: Record<string, unknown>, ...keys: string[]): string {
    for (const key of keys) if (typeof item[key] === 'string') return String(item[key]);
    return '';
}

function orderId(value: Record<string, unknown> | null): string {
    if (!value) return '';
    if (typeof value.id === 'string') return value.id;
    const order = typeof value.order === 'object' && value.order !== null ? value.order as Record<string, unknown> : null;
    return order && typeof order.id === 'string' ? order.id : '';
}

async function send(path: string, body: Record<string, unknown> = {}): Promise<void> {
    busy.value = true;
    result.value = null;
    requestId.value = null;
    try {
        const response = await fetch(`/api/account/${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': props.csrf, 'Idempotency-Key': crypto.randomUUID() },
            body: JSON.stringify(body)
        });
        responseStatus.value = response.status;
        requestId.value = response.headers.get('X-Request-ID');
        const payload: unknown = await response.json().catch(() => ({ message: response.statusText }));
        result.value = typeof payload === 'object' && payload !== null ? payload as Record<string, unknown> : { message: String(payload) };
        payment.value = orderId(result.value) ? result.value : payment.value;
    } finally {
        busy.value = false;
    }
}

async function redeem(): Promise<void> {
    const submittedSecret = secret.value;
    secret.value = '';
    await send('gift-card', { secret: submittedSecret });
}

function submitOrder(event: Event, path: 'points/orders' | 'membership/orders', key: 'product_key' | 'offer_key'): void {
    const form = new FormData(event.currentTarget as HTMLFormElement);
    void send(path, {
        [key]: String(form.get(key) ?? ''),
        provider_key: String(form.get('provider_key') ?? ''),
        ...(path === 'membership/orders' ? { renewal: form.get('renewal') === 'true' } : {})
    });
}

async function refreshPayment(id = orderId(payment.value)): Promise<void> {
    if (!id) return;
    busy.value = true;
    try {
        const response = await fetch(`/api/account/payment-orders/${encodeURIComponent(id)}`, { cache: 'no-store' });
        responseStatus.value = response.status;
        requestId.value = response.headers.get('X-Request-ID');
        const payload: unknown = await response.json().catch(() => ({ message: response.statusText }));
        payment.value = typeof payload === 'object' && payload !== null ? payload as Record<string, unknown> : null;
        result.value = payment.value;
    } finally {
        busy.value = false;
    }
}
</script>

<template>
    <div class="account-actions">
        <form v-if="section === 'points'" action="/api/account/check-ins" method="post" @submit.prevent="send('check-ins')">
            <input type="hidden" name="csrf" :value="csrf" />
            <button type="submit" :disabled="busy">{{ labels.checkIn }}</button>
        </form>

        <article v-for="item in items" :key="stringValue(item, 'product_key', 'offer_key', 'id')" class="action-card">
            <template v-if="section === 'points' && stringValue(item, 'product_key')">
                <strong>{{ stringValue(item, 'display_name', 'product_key') }}</strong>
                <p>{{ item.points_amount }} credit · CNY {{ Number(item.price_cents ?? 0) / 100 }}</p>
                <form action="/api/account/points/orders" method="post" @submit.prevent="submitOrder($event, 'points/orders', 'product_key')">
                    <input type="hidden" name="csrf" :value="csrf" /><input type="hidden" name="product_key" :value="item.product_key" />
                    <label>{{ labels.provider }}<input name="provider_key" required maxlength="100" :value="String(item.provider_key ?? '')" /></label>
                    <button type="submit" :disabled="busy || item.available === false">{{ labels.buy }}</button>
                </form>
            </template>
            <template v-else-if="section === 'membership' && stringValue(item, 'offer_key', 'level_key')">
                <strong>{{ stringValue(item, 'display_name', 'offer_key', 'level_key') }}</strong>
                <p>CNY {{ Number(item.price_cents ?? 0) / 100 }} · {{ item.cycle_days }} days · {{ item.grant_points ?? item.cycle_points_amount }} credit</p>
                <form action="/api/account/membership/orders" method="post" @submit.prevent="submitOrder($event, 'membership/orders', 'offer_key')">
                    <input type="hidden" name="csrf" :value="csrf" />
                    <label>Offer key<input name="offer_key" required maxlength="200" :value="String(item.offer_key ?? '')" /></label>
                    <label>{{ labels.provider }}<input name="provider_key" required maxlength="100" :value="String(item.provider_key ?? '')" /></label>
                    <label><input name="renewal" type="checkbox" value="true" />{{ labels.renew }}</label>
                    <button type="submit" :disabled="busy">{{ labels.buy }}</button>
                </form>
            </template>
            <template v-else-if="section === 'purchases'">
                <strong>{{ stringValue(item, 'description', 'offer_key', 'id') }}</strong>
                <p>{{ stringValue(item, 'state', 'status') }} · CNY {{ Number(item.amount ?? 0) / 100 }}</p>
                <button type="button" :disabled="busy" @click="refreshPayment(stringValue(item, 'id', 'order_id'))">{{ labels.refresh }}</button>
            </template>
            <template v-else-if="section === 'downloads'">
                <strong>{{ stringValue(item, 'target_id', 'product_ref', 'id') }}</strong>
                <p>{{ stringValue(item, 'status') }} · manifest {{ stringValue(item, 'manifest_version') }} · {{ Array.isArray(item.items) ? item.items.length : 0 }} files</p>
                <form :action="`/api/account/downloads/${encodeURIComponent(stringValue(item, 'id'))}/links`" method="post" @submit.prevent="send(`downloads/${encodeURIComponent(stringValue(item, 'id'))}/links`)">
                    <input type="hidden" name="csrf" :value="csrf" />
                    <button type="submit" :disabled="busy || item.status !== 'active'">{{ labels.links }}</button>
                </form>
            </template>
        </article>

        <form v-if="section === 'membership'" action="/api/account/membership/cancel" method="post" @submit.prevent="send('membership/cancel', { reason: String(new FormData($event.currentTarget as HTMLFormElement).get('reason') ?? '') })">
            <label>{{ labels.reason }}<input name="reason" required maxlength="500" /></label>
            <input type="hidden" name="csrf" :value="csrf" />
            <button type="submit" :disabled="busy">{{ labels.cancel }}</button>
        </form>

        <form v-if="section === 'gift-card'" action="/api/account/gift-card" method="post" autocomplete="off" @submit.prevent="redeem">
            <label>{{ labels.secret }}<input v-model="secret" name="secret" type="password" required maxlength="500" autocomplete="off" /></label>
            <input type="hidden" name="csrf" :value="csrf" />
            <button type="submit" :disabled="busy || !secret">{{ labels.redeem }}</button>
        </form>

        <section v-if="result" class="workflow-result" role="status" aria-live="polite">
            <strong>{{ String(result.status ?? result.state ?? result.code ?? `HTTP ${responseStatus}`) }}</strong>
            <p v-if="result.message">{{ String(result.message) }}</p>
            <p v-if="result.code">Code: <code>{{ String(result.code) }}</code></p>
            <p v-if="requestId">Request ID: <code>{{ requestId }}</code></p>
            <p v-if="orderId(payment)">{{ labels.pending }}</p>
            <button v-if="orderId(payment)" type="button" :disabled="busy" @click="refreshPayment()">{{ labels.refresh }}</button>
            <ul v-if="Array.isArray(result.links)" class="link-list">
                <li v-for="link in result.links as Record<string, unknown>[]" :key="String(link.item_id)">
                    <a v-if="link.status === 'redirect' && typeof link.redirect_url === 'string'" :href="link.redirect_url" rel="noreferrer">{{ String(link.item_id) }}</a>
                    <span v-else>{{ String(link.item_id) }}: {{ String(link.status) }}</span>
                    <code v-if="link.proxy_ticket">{{ String(link.proxy_ticket) }}</code>
                    <span v-if="link.reason_code">{{ String(link.reason_code) }}</span>
                </li>
            </ul>
        </section>
    </div>
</template>

<style scoped>
.account-actions { display: grid; gap: 1rem; margin-top: 1.5rem; }
.action-card, .workflow-result, form { display: grid; gap: .7rem; border-top: 1px solid var(--hairline); padding-top: 1rem; }
label { display: grid; gap: .4rem; font-weight: 700; }
input { min-height: 2.75rem; border: 1px solid var(--hairline); border-radius: .4rem; background: var(--surface-raised); color: var(--ink); padding: .65rem .75rem; }
button { width: fit-content; min-height: 2.75rem; border: 1px solid var(--ink); border-radius: 999px; background: var(--ink); color: var(--canvas); padding: .65rem 1rem; font: inherit; font-weight: 700; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .55; }
.workflow-result { border: 1px solid var(--hairline); border-left: 4px solid var(--focus); padding: 1rem; }
.link-list { display: grid; gap: .6rem; padding-left: 1.2rem; }
code { overflow-wrap: anywhere; }
</style>
