#!/usr/bin/env node
/**
 * Compile a card material profile into deterministic CSS delivery assets.
 *
 * Usage:
 *   node scripts/compile-card-profile.mjs \
 *     --profile <card-material-profile.json> \
 *     --input-dir <asset-root> \
 *     [--out generated/cards/<profile-id>] \
 *     [--publication-report path/to/check-publish-report.json] \
 *     [--prototype-report path/to/prototype-attestation.json] \
 *     [--generated-at 2026-01-01T00:00:00Z]
 *
 * Output is written to generated/cards/<profile-id>/ by default. generated/
 * is git-ignored; compiled artifacts are never committed.
 */

import path from "node:path";
import process from "node:process";

import { CompileRefusal, compileCardProfile } from "./lib/profile-compiler.mjs";

function parseArgs(argv) {
  const options = {};
  const flags = {
    "--profile": "profilePath",
    "--input-dir": "inputDir",
    "--out": "outDir",
    "--publication-report": "publicationReportPath",
    "--prototype-report": "prototypeReportPath",
    "--generated-at": "generatedAt"
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = flags[argv[index]];
    if (!key) throw new CompileRefusal(`unknown argument: ${argv[index]}`);
    const value = argv[index + 1];
    if (value === undefined) throw new CompileRefusal(`${argv[index]} requires a value`);
    options[key] = value;
    index += 1;
  }
  return options;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (!options.profilePath || !options.inputDir) {
    throw new CompileRefusal(
      "Usage: compile-card-profile --profile <profile.json> --input-dir <dir> " +
        "[--out <dir>] [--publication-report <report.json>] " +
        "[--prototype-report <report.json>] [--generated-at <iso>]"
    );
  }

  if (!options.outDir) {
    const { default: fs } = await import("node:fs/promises");
    const profile = JSON.parse(await fs.readFile(options.profilePath, "utf8"));
    const id = String(profile?.card?.id ?? "");
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/.test(id)) {
      throw new CompileRefusal(`profile card.id is not a safe output identifier: ${id}`);
    }
    options.outDir = path.join("generated", "cards", id);
  }

  const result = await compileCardProfile(options);
  console.log(`compiled ${result.manifest.profile.id} [${result.state}] → ${result.outDir}`);
  if (result.manifest.notice) console.log(`notice: ${result.manifest.notice}`);
  if (result.manifest.webglHandoff) {
    console.log(`webgl handoff: ${result.manifest.webglHandoff.reasons.join("; ")}`);
  }
}

main().catch((error) => {
  console.error(error instanceof CompileRefusal ? `refused: ${error.message}` : error.stack);
  process.exitCode = 1;
});
