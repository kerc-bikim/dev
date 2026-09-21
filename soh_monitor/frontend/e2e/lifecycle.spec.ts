/**
 * Playwright 수명주기. 브라우저가 있을 때만 돈다.
 * 기본 게이트는 backend/tests/e2e/test_lifecycle.py (API+수집기) 다.
 *
 *   E2E_BASE_URL=http://127.0.0.1:5173 npx playwright test
 */
import { expect, test } from "@playwright/test";

const base = process.env.E2E_BASE_URL;

test.skip(!base, "E2E_BASE_URL 이 없으면 건너뛴다");

test("로그인 후 통합 현황과 Grafana 링크가 보인다", async ({ page }) => {
  await page.goto(`${base}/login`);
  await page.getByLabel("사용자").fill(process.env.E2E_USER ?? "admin");
  await page.getByLabel("비밀번호").fill(process.env.E2E_PASSWORD ?? "admin-changed-123");
  await page.getByRole("button", { name: /로그인/ }).click();
  await expect(page.getByRole("heading", { name: "통합 현황" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Grafana 함대" })).toHaveAttribute(
    "href",
    "/grafana/d/01-fleet-overview",
  );
});
