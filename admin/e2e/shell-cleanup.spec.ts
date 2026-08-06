import { expect, test } from '@playwright/test'

async function login(page: import('@playwright/test').Page) {
  await page.goto('/account/login')
  const inputs = page.locator('input')
  await inputs.nth(0).fill('admin')
  await inputs.nth(1).fill('admin1234')
  await page.locator('button[type="submit"]').click()
  await expect(page).toHaveURL(/\/$/)
}

test.describe('application shell preferences', () => {
  test('keeps only Chinese and English and removes legacy customization controls', async ({ page }) => {
    await login(page)

    await page.getByTestId('language-select-toggle').click()
    await expect(page.getByText('中文', { exact: true })).toBeVisible()
    await expect(page.getByText('英语', { exact: true })).toBeVisible()
    await expect(page.getByText('波斯语', { exact: true })).toHaveCount(0)

    await page.keyboard.press('Escape')
    await page.getByTestId('theme-customize-toggle').click()
    await expect(page.locator('input[type="color"]')).toHaveCount(0)
    await expect(page.getByText('扁平化设计', { exact: true })).toHaveCount(0)
    await expect(page.locator('[data-theme-color]')).toHaveCount(7)
    await expect(page.getByText('RTL布局', { exact: true })).toBeVisible()
  })

  test('persists a selected preset theme color', async ({ page }) => {
    await login(page)
    await page.getByTestId('theme-customize-toggle').click()
    await page.locator('[data-theme-color="#DB0B51"]').dispatchEvent('click')

    await expect
      .poll(() =>
        page.evaluate(() =>
          getComputedStyle(document.documentElement)
            .getPropertyValue('--primary-color')
            .trim(),
        ),
      )
      .toBe('#DB0B51')
    await expect
      .poll(() =>
        page.evaluate(() => JSON.parse(localStorage.getItem('layout') ?? '{}').themeColor),
      )
      .toBe('#DB0B51')
  })
})
