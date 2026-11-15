import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";

// Parent loop on a phone: consent -> paragraph card -> child reads (fake mic plays a real clip) ->
// marked words -> story card -> final level on the ladder + tonight's practice.
// The "microphone" plays a real clip from its start when recording begins (Chrome's own fake device
// loops from browser launch, so a recording could start mid-sentence). Recording, upload, speech
// model and scoring are all real.
async function micPlays(page, clip: string) {
  const b64 = fs.readFileSync(path.resolve(__dirname, "../tests/fixtures", clip)).toString("base64");
  await page.addInitScript((data) => {
    navigator.mediaDevices.getUserMedia = async () => {
      const ctx = new AudioContext();
      const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
      const buf = await ctx.decodeAudioData(bytes.buffer);
      const src = ctx.createBufferSource(); src.buffer = buf;
      const dest = ctx.createMediaStreamDestination(); src.connect(dest); src.start();
      return dest.stream;
    };
  }, b64);
}

test("parent checks a child's reading level", async ({ page }) => {
  await micPlays(page, "paragraph-18.wav");
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
  const before = await (await request.get("/api/impact")).json();
  const t = await (await request.post("/api/teacher", { data: { name: "Test class" } })).json();
  const s = await (await request.post("/api/session", { data: { klass: 2, consent: true, child_key: "e2e-child", teacher_code: t.code, set_id: "A" } })).json();
  const clip = (f: string) => ({ name: f, mimeType: "audio/wav", buffer: fs.readFileSync(path.resolve(__dirname, "../tests/fixtures", f)) });
  let r = await request.post("/api/read", { multipart: { session_id: s.session_id, level: "paragraph", audio: clip("story-39.wav") } });
  expect((await r.json()).next_level).toBe("word");
  r = await request.post("/api/read", { multipart: { session_id: s.session_id, level: "word", audio: clip("word-13.wav") } });
  const reading = await r.json();
  expect(reading.needs_teacher).toBe(true);
  // the class code alone (what parents have) is refused
  expect((await request.get(`/api/teacher/${t.code}/queue`)).status()).toBe(403);
  await page.goto(`/teacher/${t.code}#k=${t.key}`);    // the teacher's private link
  await expect(page.locator("#share")).toContainText("?t=" + t.code);
  const card = page.locator("#items .card").first();
  await expect(card).toContainText("शब्द");
  await card.locator(".marked span.bad").first().click(); // teacher hears this word was read right
  await card.getByRole("button", { name: "पक्का करें" }).click();
  await expect(page.locator("#items")).toContainText("पक्का हो गया");
  // the class-planner agent writes tomorrow's plan from the class data
  await page.locator("#plan-btn").click();
  await expect(page.locator("#plan")).toContainText("शब्द", { timeout: 120_000 });
  const st = await (await request.get("/api/session/" + s.session_id)).json();
  expect(st.teacher_checked).toBe(true);
  // our own runs carry the test token and must never move the public impact numbers
  const imp = await (await request.get("/api/impact")).json();
  if (process.env.TEST_TOKEN) expect(imp.teacher_checked).toBe(before.teacher_checked);
});
