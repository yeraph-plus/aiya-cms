import redisDriver from 'unstorage/drivers/redis';

export default function createRedisSessionDriver() {
    const url = process.env.SITE_REDIS_URL?.trim() || 'redis://127.0.0.1:6379/1';
    if (!url.startsWith('redis://') && !url.startsWith('rediss://')) {
        throw new Error('SITE_REDIS_URL must use redis:// or rediss://');
    }
    return redisDriver({
        url,
        base: 'aiya:site:sessions',
        preConnect: false,
        ttl: 60 * 60 * 24 * 7
    });
}
