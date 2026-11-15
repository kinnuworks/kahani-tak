import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

// Parent loop on a phone: consent -> paragraph card -> child reads (fake mic plays a real clip) ->
// marked words -> story card -> final level on the ladder + tonight's practice.
test("parent checks a child's reading level", async ({ page }) => {
  await page.goto("/?set=A");                       // the fake microphone reads card set A
  await expect(page.getByRole("heading", { name: /Kahani Tak/ })).toBeVisible();
  await expect(page.locator("#begin")).toBeDisabled();
  await page.locator("#consent").check();
  await page.locator("#begin").click();
  await expect(page.locator("#card")).toContainText("रानी");
  await page.locator("#rec").click();
  await page.waitForTimeout(8000);                    // clip is ~6.5 s
  await page.locator("#rec").click();
  await expect(page.locator("#marked span.ok").first()).toBeVisible({ timeout: 90_000 });
  await expect(page.locator("#verdict")).toBeVisible();
  await page.locator("#next").click();                 // paragraph passed -> story (ASER path)
  await expect(page.locator("#card")).toContainText("सोनू");
  await page.locator("#rec").click();
  await page.waitForTimeout(8000);                    // same clip: reads the wrong text, so the story fails
  await page.locator("#rec").click();
  await expect(page.locator("#final-line")).toContainText("अनुच्छेद तक", { timeout: 90_000 });
  await expect(page.locator("#ladder li.here")).toHaveText("अनुच्छेद");
  await expect(page.locator("#practice h3")).toContainText("आज रात 5 मिनट");
});

// Teacher confirms an unsure reading; the parent's session updates.
test("teacher checks an unsure reading", async ({ page, request }) => {
  const t = await (await request.post("/api/teacher", { data: { name: "Test class" } })).json();
  const s = await (await request.post("/api/session", { data: { klass: 2, consent: true, child_key: "e2e-child", teacher_code: t.code, set_id: "A" } })).json();
  const clip = (f: string) => ({ name: f, mimeType: "audio/wav", buffer: fs.readFileSync(path.resolve(__dirname, "../tests/fixtures", f)) });
  let r = await request.post("/api/read", { multipart: { session_id: s.session_id, level: "paragraph", audio: clip("story-39.wav") } });
  expect((await r.json()).next_level).toBe("word");
  r = await request.post("/api/read", { multipart: { session_id: s.session_id, level: "word", audio: clip("word-13.wav") } });
  const reading = await r.json();
  expect(reading.needs_teacher).toBe(true);
  await page.goto("/teacher/" + t.code);
  await expect(page.locator("#share")).toContainText("?t=" + t.code);
  const card = page.locator("#items .card").first();
  await expect(card).toContainText("शब्द");
  await card.locator(".marked span").first().click();   // teacher flips one word
  await card.getByRole("button", { name: "पक्का करें" }).click();
  await expect(page.locator("#items")).toContainText("पक्का हो गया");
  const st = await (await request.get("/api/session/" + s.session_id)).json();
  expect(st.teacher_checked).toBe(true);
  const imp = await (await request.get("/api/impact")).json();
  expect(imp.teacher_checked).toBeGreaterThanOrEqual(1);
});
