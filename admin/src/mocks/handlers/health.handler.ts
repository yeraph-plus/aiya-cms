import { HttpResponse, http } from 'msw'

const health = {
  status: 'ok',
  environment: 'mocking',
  version: '0.1.0',
  dependencies: { postgres: 'ok', redis: 'ok' },
}

const handlers = [
  http.get('*/healthz', () => HttpResponse.json({ status: 'ok' })),
  http.get('*/api/v1/health', () => HttpResponse.json(health)),
]

export default handlers
