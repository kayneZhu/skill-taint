import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { skillChannels } from "./dist/channel.js";
import { parseSummaries } from "./dist/parse.js";
import { loadSummaryDocuments, startViewer } from "./server.mjs";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const summariesDir = join(repoRoot, "results", "summaries");
const viewerDir = fileURLToPath(new URL(".", import.meta.url));

await rejectBadDirectories();
await rejectUnsafeRendering();
await loadThroughHttp();

async function rejectBadDirectories() {
  const empty = await mkdtemp(join(tmpdir(), "skill-taint-empty-"));
  try {
    await assert.rejects(loadSummaryDocuments(empty), /no campaign summaries/);
  } finally {
    await rm(empty, { recursive: true });
  }

  const stray = await mkdtemp(join(tmpdir(), "skill-taint-stray-"));
  try {
    await writeFile(join(stray, "note.txt"), "x");
    await assert.rejects(loadSummaryDocuments(stray), /unexpected summary entry: note.txt/);
  } finally {
    await rm(stray, { recursive: true });
  }

  const mismatch = await mkdtemp(join(tmpdir(), "skill-taint-id-"));
  try {
    await writeFile(
      join(mismatch, "opus__policy__off__r0.json"),
      JSON.stringify({ campaign_id: "other" }),
    );
    await assert.rejects(loadSummaryDocuments(mismatch), /campaign_id is other/);
  } finally {
    await rm(mismatch, { recursive: true });
  }
}

async function rejectUnsafeRendering() {
  const source = await readFile(join(viewerDir, "src", "render.ts"), "utf8");
  for (const token of ["innerHTML", "insertAdjacentHTML", "document.write"]) {
    assert.equal(source.includes(token), false, `render.ts contains ${token}`);
  }
}

async function loadThroughHttp() {
  const documents = await loadSummaryDocuments(summariesDir);
  const viewer = await startViewer({ port: 0, host: "127.0.0.1" });
  try {
    const index = await fetchOk(viewer.url, "/");
    const html = await index.text();
    assert.match(html, /id="app"/);
    assert.match(html, /\/assets\/main\.js/);
    assert.match(html, /\/styles\.css/);

    const css = await fetchOk(viewer.url, "/styles.css");
    assert.match(await css.text(), /\.badge-t/);

    const script = await fetchOk(viewer.url, "/assets/main.js");
    const scriptText = await script.text();
    assert.match(scriptText, /mountApp/);
    assert.equal(scriptText.includes("innerHTML"), false);

    const missingAsset = await fetch(new URL("/assets/parse.test.js", viewer.url));
    assert.equal(missingAsset.status, 404);
    const missingFile = await fetch(new URL("/assets/notreal.js", viewer.url));
    assert.equal(missingFile.status, 404);
    const traversal = await fetch(new URL("/assets/../server.mjs", viewer.url));
    assert.equal(traversal.status, 404);
    const posted = await fetch(new URL("/api/summaries", viewer.url), { method: "POST" });
    assert.equal(posted.status, 405);

    const response = await fetchOk(viewer.url, "/api/summaries");
    const payload = await response.json();
    assert.deepEqual(payload, documents);
    const campaigns = parseSummaries(payload);
    assert.equal(campaigns.length, documents.length);
    const campaign = campaigns.find((item) => item.campaignId === "opus__formal__quarantine__r2");
    assert.ok(campaign);
    const channel = skillChannels(campaign).find((item) => item.skillId === "skill-592c6d638af0");
    assert.ok(channel);
    assert.equal(channel.label, "untrusted");
    assert.equal(channel.decision.kind, "omitted-untrusted");
  } finally {
    await viewer.close();
  }
}

async function fetchOk(origin, pathname) {
  const response = await fetch(new URL(pathname, origin));
  if (!response.ok) {
    throw new Error(`${pathname} returned ${response.status}: ${await response.text()}`);
  }
  return response;
}
