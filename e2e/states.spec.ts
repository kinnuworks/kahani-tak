import { test, expect } from "@playwright/test";

// Every state in the design brief is reachable with ?state= (for design work and screenshots).
// Previews show example data and say so on screen; they never call the speech model or write data.
const PARENT: Record<string, string> = {
  start: "#begin",
  read: "#rec",
  recording: "#rec.on",
  checking: "#rec-status",
  "result-pass": "#marked span.ok",
  "result-teacher": "#verdict",
  "final-story": "#ladder li.here",
  "final-paragraph": "#ladder li.here",
  "final-word": "#ladder li.here",
  "final-letter": "#ladder li.here",
  "final-beginner": "#final-line",
  "final-waiting": "#teacher-status",
  "final-checked": "#teacher-status",
  "error-mic": "#error",
  "error-nothing-heard": "#error",
  "error-network": "#error",
  "error-server": "#error",
};
const TEACHER: Record<string, string> = {
  create: "#create",
  queue: "#items .card",
  "queue-empty": "#counts",
  "plan-loading": "#plan",
  plan: "#plan",
  "wrong-key": ".error",
};

for (const [state, sel] of Object.entries(PARENT)) {
  test(`parent state ${state}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`/?state=${state}`);
    await expect(page.locator(sel).first()).toBeVisible();
    await expect(page.locator("#preview-banner")).toBeVisible();
    expect(errors).toEqual([]);
  });
}

for (const [state, sel] of Object.entries(TEACHER)) {
  test(`teacher state ${state}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`/teacher?state=${state}`);
    await expect(page.locator(sel).first()).toBeVisible();
    await expect(page.locator("#preview-banner")).toBeVisible();
    expect(errors).toEqual([]);
  });
}

for (const state of ["empty", "filled"]) {
  test(`impact state ${state}`, async ({ page }) => {
    await page.goto(`/impact?state=${state}`);
    await expect(page.locator("#grid .num").first()).toBeVisible();
    await expect(page.locator("#preview-banner")).toBeVisible();
  });
}

test("first screen shows a labelled example result", async ({ page }) => {
  await page.goto("/");
  const ex = page.locator("#example");
  await expect(ex.locator(".marked span.bad").first()).toBeVisible();
  await expect(ex).toContainText("उदाहरण");
  await expect(ex).toContainText("कंप्यूटर की आवाज़");   // says it is a synthetic voice, not a child
});
