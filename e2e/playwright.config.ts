import { defineConfig } from "@playwright/test";
import path from "path";
const local = !process.env.BASE_URL;
export default defineConfig({
  testDir: ".",
  timeout: 240_000,
  outputDir: "results",
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL || "http://127.0.0.1:8765",
    video: "on",                       // rough cut of the real demo path
    viewport: { width: 412, height: 915 },   // a phone
    locale: "hi-IN",
    launchOptions: { args: [
      "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
    ] },
  },
  webServer: local ? {
    command: "cd .. && DATA_DIR=$(mktemp -d) .venv/bin/uvicorn kahani.server:app --port 8765",
    url: "http://127.0.0.1:8765/healthz", timeout: 180_000, reuseExistingServer: false,
  } : undefined,
});
