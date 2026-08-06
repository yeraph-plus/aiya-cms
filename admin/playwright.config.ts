import { defineConfig, devices } from '@playwright/test'

const realRuntime = process.env.AIYA_E2E_REAL === 'true'
const baseURL = process.env.AIYA_E2E_BASE_URL ?? 'http://localhost:7000'
const useWebServer = process.env.AIYA_E2E_WEB_SERVER !== 'false'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile',
      use: { ...devices['Pixel 5'] },
    },
  ],
  ...(useWebServer
    ? {
        webServer: {
          command: realRuntime
            ? 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 7000 --mode development'
            : 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 7000 --mode mocking',
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      }
    : {}),
})
