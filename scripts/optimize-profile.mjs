#!/usr/bin/env node
import { execFile, spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import {
  coordinateCandidates,
  createOptimizerState,
  nextStep,
  profileCacheKey,
  profileParameterSnapshot,
  validateParameterSpecs
} from "./lib/profile-optimizer.mjs";

const execFileAsync = promisify(execFile);
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const defaultProjectRoot = path.resolve(scriptDirectory, "..");

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function safeSlug(value, label = "id") {
  const slug = String(value ?? "").toLowerCase();
  if (!/^[a-z0-9][a-z0-9._-]{1,95}$/.test(slug)) {
    throw new Error(`${label} must be a lowercase slug`);
  }
  return slug;
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

async function resolveJson(value, directory, label) {
  if (typeof value === "string") return readJson(path.resolve(directory, value));
  if (!value || typeof value !== "object") throw new Error(`${label} is required`);
  return clone(value);
}

function relativeInside(root, target, label) {
  const relative = path.relative(root, target);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`${label} must be a child of the session root`);
  }
  return relative.split(path.sep).join("/");
}

function validateProfileCouplings(profile) {
  const renderer = profile.renderer ?? {};
  const minimum = Number(renderer.iridescenceThicknessMinNm);
  const maximum = Number(renderer.iridescenceThicknessMaxNm);
  if (Number.isFinite(minimum) && Number.isFinite(maximum) && minimum > maximum) {
    throw new Error("iridescenceThicknessMinNm may not exceed iridescenceThicknessMaxNm");
  }
}

async function runLogged(command, args, { cwd, logPath, env } = {}) {
  try {
    const result = await execFileAsync(command, args, {
      cwd,
      env: { ...process.env, ...(env ?? {}) },
      maxBuffer: 32 * 1024 * 1024
    });
    await fs.writeFile(
      logPath,
      `${result.stdout ?? ""}${result.stderr ? `\n[stderr]\n${result.stderr}` : ""}`
    );
    return result;
  } catch (error) {
    const output = `${error.stdout ?? ""}${error.stderr ? `\n[stderr]\n${error.stderr}` : ""}`;
    await fs.writeFile(logPath, output);
    throw new Error(`${command} failed; see ${logPath}: ${error.message}`);
  }
}

async function urlIsReady(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(2500) });
    return response.ok;
  } catch {
    return false;
  }
}

async function waitForUrl(url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await urlIsReady(url)) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`renderer server did not become ready: ${url}`);
}

async function ensureRendererServer(baseUrl, projectRoot, startServer) {
  if (await urlIsReady(baseUrl)) return null;
  if (!startServer) throw new Error(`renderer server is not available: ${baseUrl}`);

  const parsed = new URL(baseUrl);
  const host = parsed.hostname;
  const port = parsed.port || (parsed.protocol === "https:" ? "443" : "80");
  const child = spawn(
    "npm",
    ["run", "dev", "--", "--host", host, "--port", port],
    {
      cwd: projectRoot,
      detached: process.platform !== "win32",
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"]
    }
  );
  let serverLog = "";
  child.stdout.on("data", (chunk) => {
    serverLog += chunk.toString();
  });
  child.stderr.on("data", (chunk) => {
    serverLog += chunk.toString();
  });

  try {
    await waitForUrl(baseUrl);
  } catch (error) {
    child.kill("SIGTERM");
    throw new Error(`${error.message}\n${serverLog}`);
  }
  return child;
}

function stopRendererServer(child) {
  if (!child?.pid) return;
  try {
    if (process.platform === "win32") child.kill("SIGTERM");
    else process.kill(-child.pid, "SIGTERM");
  } catch {
    child.kill("SIGTERM");
  }
}

function candidatePathForFrame(trialRelative, frameId) {
  return `${trialRelative}/candidate/${safeSlug(frameId, "frame id")}.png`;
}

async function main() {
  const requestPath = process.argv[2];
  if (!requestPath) throw new Error("Usage: node scripts/optimize-profile.mjs <request.json>");

  const absoluteRequestPath = path.resolve(requestPath);
  const requestDirectory = path.dirname(absoluteRequestPath);
  const request = await readJson(absoluteRequestPath);
  const runId = safeSlug(request.runId, "runId");
  const sessionRoot = path.resolve(requestDirectory, request.sessionRoot ?? ".");
  const webProjectRoot = path.resolve(
    requestDirectory,
    request.webProjectRoot ?? defaultProjectRoot
  );
  const outputRoot = path.resolve(sessionRoot, request.outputDirectory ?? `review/optimization/${runId}`);
  const outputRelative = relativeInside(sessionRoot, outputRoot, "outputDirectory");
  const baseProfile = await resolveJson(request.baseProfile, requestDirectory, "baseProfile");
  const renderTemplate = await resolveJson(request.renderTemplate, requestDirectory, "renderTemplate");
  const fitTemplate = await resolveJson(request.fitTemplate, requestDirectory, "fitTemplate");
  const specs = validateParameterSpecs(request.parameters);
  const maxPasses = Math.max(1, Math.min(Number(request.maxPasses ?? 4), 20));
  const maxTrials = Math.max(1, Math.min(Number(request.maxTrials ?? 80), 500));
  const tolerance = Math.max(0, Number(request.improvementTolerance ?? 0.0005));
  validateProfileCouplings(baseProfile);

  const frameIds = (renderTemplate.frames ?? []).map((frame) => safeSlug(frame.id, "render frame id"));
  const fitFrameIds = (fitTemplate.frames ?? []).map((frame) => safeSlug(frame.frame_id, "fit frame id"));
  if (!frameIds.length || JSON.stringify(frameIds) !== JSON.stringify(fitFrameIds)) {
    throw new Error("renderTemplate and fitTemplate frame ids must be non-empty and ordered identically");
  }

  await fs.mkdir(path.join(outputRoot, "trials"), { recursive: true });
  const baseUrl = renderTemplate.baseUrl ?? "http://127.0.0.1:4173";
  const server = await ensureRendererServer(
    baseUrl,
    webProjectRoot,
    request.startServer !== false
  );

  const state = createOptimizerState(baseProfile, specs);
  const cache = new Map();
  let trialCounter = 0;

  async function evaluate(profile, reason) {
    validateProfileCouplings(profile);
    const key = profileCacheKey(profile, specs);
    const cached = cache.get(key);
    if (cached) return cached;
    if (trialCounter >= maxTrials) throw new Error(`maximum trial count reached: ${maxTrials}`);

    trialCounter += 1;
    const trialId = `trial-${String(trialCounter).padStart(4, "0")}`;
    const trialRoot = path.join(outputRoot, "trials", trialId);
    const trialRelative = relativeInside(sessionRoot, trialRoot, "trial directory");
    await fs.mkdir(trialRoot, { recursive: true });

    const profilePath = path.join(trialRoot, "profile.json");
    await fs.writeFile(profilePath, `${JSON.stringify(profile, null, 2)}\n`);

    const renderRequest = {
      ...clone(renderTemplate),
      profile,
      outputDirectory: "candidate",
      pythonProjectRoot: webProjectRoot,
      canonicalize: true,
      retainPerspective: Boolean(request.retainPerspective)
    };
    const renderRequestPath = path.join(trialRoot, "render-request.json");
    await fs.writeFile(renderRequestPath, `${JSON.stringify(renderRequest, null, 2)}\n`);
    await runLogged(
      "npm",
      ["run", "render:sequence", "--", renderRequestPath],
      {
        cwd: webProjectRoot,
        logPath: path.join(trialRoot, "render.log")
      }
    );

    const fitRequest = clone(fitTemplate);
    fitRequest.run_id = safeSlug(`${runId}-${trialId}`, "fit run id");
    fitRequest.session_id = fitTemplate.session_id;
    fitRequest.profile_path = `${trialRelative}/profile.json`;
    fitRequest.output_path = `${trialRelative}/fit-report.json`;
    fitRequest.frames = fitRequest.frames.map((frame) => ({
      ...frame,
      candidate_path: candidatePathForFrame(trialRelative, frame.frame_id)
    }));
    const fitRequestPath = path.join(trialRoot, "fit-request.json");
    await fs.writeFile(fitRequestPath, `${JSON.stringify(fitRequest, null, 2)}\n`);
    await runLogged(
      request.uvExecutable ?? "uv",
      ["run", "optcg-fit", "evaluate", sessionRoot, fitRequestPath],
      {
        cwd: webProjectRoot,
        logPath: path.join(trialRoot, "fit.log")
      }
    );

    const report = await readJson(path.join(trialRoot, "fit-report.json"));
    const trial = {
      trialId,
      reason,
      cacheKey: key,
      aggregateLoss: Number(report.aggregate_loss),
      parameters: profileParameterSnapshot(profile, specs),
      profilePath: `${trialRelative}/profile.json`,
      fitReportPath: `${trialRelative}/fit-report.json`
    };
    state.trials.push(trial);
    cache.set(key, { profile: clone(profile), report, trial });
    await fs.writeFile(
      path.join(outputRoot, "optimization-progress.json"),
      `${JSON.stringify({ runId, outputRelative, ...state }, null, 2)}\n`
    );
    return cache.get(key);
  }

  try {
    let current = await evaluate(state.profile, "baseline");
    state.profile = current.profile;
    state.bestLoss = current.trial.aggregateLoss;
    state.bestTrialId = current.trial.trialId;

    for (let pass = 1; pass <= maxPasses && trialCounter < maxTrials; pass += 1) {
      let passImproved = false;
      for (const spec of specs) {
        const step = state.steps[spec.name];
        if (spec.locked || step <= 0 || trialCounter >= maxTrials) continue;

        const proposals = coordinateCandidates(state.profile, spec, step);
        let bestForCoordinate = current;
        for (const proposal of proposals) {
          if (trialCounter >= maxTrials) break;
          try {
            const candidate = await evaluate(proposal, `pass-${pass}:${spec.name}`);
            if (candidate.trial.aggregateLoss < bestForCoordinate.trial.aggregateLoss) {
              bestForCoordinate = candidate;
            }
          } catch (error) {
            if (String(error.message).includes("ThicknessMinNm")) continue;
            throw error;
          }
        }

        if (
          bestForCoordinate.trial.aggregateLoss
          < current.trial.aggregateLoss - tolerance
        ) {
          current = bestForCoordinate;
          state.profile = clone(current.profile);
          state.bestLoss = current.trial.aggregateLoss;
          state.bestTrialId = current.trial.trialId;
          passImproved = true;
        } else {
          state.steps[spec.name] = nextStep(step, spec);
        }
      }

      const activeSteps = specs.some(
        (spec) => !spec.locked && state.steps[spec.name] > 0
      );
      if (!activeSteps) break;
      if (!passImproved && pass === maxPasses) break;
    }

    const bestProfilePath = path.join(outputRoot, "best-profile.json");
    await fs.writeFile(bestProfilePath, `${JSON.stringify(state.profile, null, 2)}\n`);
    const finalReport = {
      schemaVersion: "1.0.0",
      runId,
      generatedAt: new Date().toISOString(),
      sessionRoot,
      outputRelative,
      bestLoss: state.bestLoss,
      bestTrialId: state.bestTrialId,
      bestProfilePath: relativeInside(sessionRoot, bestProfilePath, "best profile"),
      finalParameters: profileParameterSnapshot(state.profile, specs),
      steps: state.steps,
      specifications: specs,
      trials: state.trials
    };
    await fs.writeFile(
      path.join(outputRoot, "optimization-report.json"),
      `${JSON.stringify(finalReport, null, 2)}\n`
    );
    console.log(JSON.stringify(finalReport, null, 2));
  } finally {
    stopRendererServer(server);
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
