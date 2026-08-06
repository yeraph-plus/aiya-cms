import { expect, test } from '@playwright/test'

test.describe('real FastAPI session shell', () => {
  test.skip(
    process.env.AIYA_E2E_REAL !== 'true',
    'Run through npm run test:e2e:real with Docker and FastAPI available.',
  )

  test('registers, restores, and logs out through the real backend', async ({ page }) => {
    const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
    const username = `e2e_${suffix}`
    const email = `${username}@example.com`
    const password = 'real-e2e-password'

    await page.goto('/account/register')
    const inputs = page.locator('input')
    await inputs.nth(0).fill(username)
    await inputs.nth(1).fill(email)
    await inputs.nth(2).fill(password)
    await page.locator('button[type="submit"]').click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByText('服务健康状态')).toBeVisible()

    await page.reload()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByText('服务健康状态')).toBeVisible()

    await page.locator('img[alt="avatar"]').click()
    await page.getByText('退出', { exact: true }).click()
    await expect(page).toHaveURL(/\/account\/login$/)

    await page.goto('/users')
    await expect(page).toHaveURL(/\/account\/login\?redirect=(?:%2F|\/)users$/)
  })
})
