import { expect, test } from '@playwright/test'

async function login(page: import('@playwright/test').Page) {
  await page.goto('/account/login')
  const inputs = page.locator('input')
  await inputs.nth(0).fill('admin')
  await inputs.nth(1).fill('admin1234')
  const loginResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/auth/login') && response.status() === 200,
  )
  await page.locator('button[type="submit"]').click()
  const payload = await (await loginResponse).json()
  await page.context().addCookies([
    {
      name: 'aiya_refresh',
      value: payload.refresh_token,
      domain: 'localhost',
      path: '/api/v1/auth',
      httpOnly: true,
      sameSite: 'Strict',
    },
  ])
  await expect(page).toHaveURL(/\/$/)
  return payload
}

test.describe('A1 session shell', () => {
  test('logs in, restores from refresh cookie, and logs out', async ({ page }) => {
    const tokens = await login(page)
    await expect(page.getByText('服务健康状态')).toBeVisible()

    // Browser service workers do not persist Set-Cookie from an MSW response;
    // keep the contract test deterministic while still exercising refresh + me.
    await page.route('**/api/v1/auth/refresh', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(tokens),
      }),
    )
    await page.reload()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByText('服务健康状态')).toBeVisible()

    await page.locator('img[alt="avatar"]').click()
    await page.getByText('退出').click()
    await expect(page).toHaveURL(/\/account\/login$/)
  })

  test('redirects an unauthenticated user from a protected route', async ({ page }) => {
    await page.goto('/users')
    await expect(page).toHaveURL(/\/account\/login\?redirect=(?:%2F|\/)users$/)
  })
})
