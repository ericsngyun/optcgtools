import { readFile } from "node:fs/promises";

const expected = "acb1197633e749a1fba4412231db2f6581586d00";
const pin = (await readFile(new URL("../upstream/PINNED_SOURCE.md", import.meta.url), "utf8")).trim();

if (!pin.includes(expected)) {
  console.error(`Expected upstream pin ${expected}.`);
  process.exit(1);
}

console.log(`Upstream source pin verified: ${expected}`);
