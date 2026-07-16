import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { test } from "@playwright/test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

for (const script of ["scripts/render-sequence.mjs", "scripts/optimize-profile.mjs"]) {
  test(`node syntax is valid: ${script}`, () => {
    execFileSync(process.execPath, ["--check", path.join(root, script)], {
      cwd: root,
      stdio: "pipe"
    });
  });
}
