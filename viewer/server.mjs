import { realpathSync } from "node:fs";
import { readFile, readdir } from "node:fs/promises";
import { createServer } from "node:http";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const viewerDir = fileURLToPath(new URL(".", import.meta.url));
const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const summariesDir = join(repoRoot, "results", "summaries");
const distDir = join(viewerDir, "dist");

export async function loadSummaryDocuments(directory) {
  if (typeof directory !== "string" || directory.length === 0) {
    throw new Error("summaries directory is required");
  }
  const entries = await readdir(directory, { withFileTypes: true });
  const names = [];
  for (const entry of entries) {
    if (entry.name.startsWith(".")) {
      throw new Error(`unexpected hidden entry in summaries: ${entry.name}`);
    }
    if (!entry.isFile()) {
      throw new Error(`unexpected non-file in summaries: ${entry.name}`);
    }
    if (!entry.name.endsWith(".json")) {
      throw new Error(`unexpected summary entry: ${entry.name}`);
    }
    names.push(entry.name);
  }
  names.sort();
  if (names.length === 0) {
    throw new Error(`no campaign summaries in ${directory}`);
  }
  const documents = [];
  for (const name of names) {
    const bytes = await readFile(join(directory, name));
    let text;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`${name}: ${message}`);
    }
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`${name}: ${message}`);
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error(`${name}: summary is not a JSON object`);
    }
    const stem = name.slice(0, -".json".length);
    if (typeof parsed.campaign_id !== "string") {
      throw new Error(`${name}: campaign_id must be a string`);
    }
    if (parsed.campaign_id !== stem) {
      throw new Error(`${name}: campaign_id is ${parsed.campaign_id}`);
    }
    documents.push(parsed);
  }
  return documents;
}

export async function startViewer({ port, host }) {
  if (typeof port !== "number" || !Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error(`port must be an integer from 0 to 65535, got ${port}`);
  }
  if (host !== "127.0.0.1") {
    throw new Error(`host must be 127.0.0.1, got ${host}`);
  }
  const server = createServer((request, response) => {
    handle(request, response).catch((error) => {
      const message = error instanceof Error ? error.message : String(error);
      if (!response.headersSent) {
        sendJson(response, 500, { error: message });
        return;
      }
      response.destroy(error instanceof Error ? error : new Error(message));
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.off("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("viewer did not bind a TCP port");
  }
  return {
    url: `http://${host}:${address.port}`,
    close() {
      return new Promise((resolve, reject) => {
        server.close((error) => {
          if (error) {
            reject(error);
            return;
          }
          resolve();
        });
      });
    },
  };
}

async function handle(request, response) {
  if (request.method !== "GET") {
    sendJson(response, 405, { error: `method ${request.method ?? ""} is not allowed` });
    return;
  }
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  if (url.pathname === "/api/summaries") {
    sendJson(response, 200, await loadSummaryDocuments(summariesDir));
    return;
  }
  if (url.pathname === "/" || url.pathname === "/index.html") {
    await sendFile(response, join(viewerDir, "index.html"), "text/html; charset=utf-8");
    return;
  }
  if (url.pathname === "/styles.css") {
    await sendFile(response, join(viewerDir, "styles.css"), "text/css; charset=utf-8");
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    const name = url.pathname.slice("/assets/".length);
    if (!/^[a-z]+\.js$/.test(name)) {
      sendText(response, 404, `unknown asset ${name}`);
      return;
    }
    try {
      await sendFile(response, join(distDir, name), "text/javascript; charset=utf-8");
    } catch (error) {
      if (isNotFound(error)) {
        sendText(response, 404, `missing asset ${name}`);
        return;
      }
      throw error;
    }
    return;
  }
  sendText(response, 404, `not found: ${url.pathname}`);
}

async function sendFile(response, path, contentType) {
  const body = await readFile(path);
  response.writeHead(200, {
    "content-type": contentType,
    "content-length": body.byteLength,
    "cache-control": "no-store",
  });
  response.end(body);
}

function sendJson(response, status, payload) {
  sendText(response, status, JSON.stringify(payload), "application/json; charset=utf-8");
}

function sendText(response, status, text, contentType = "text/plain; charset=utf-8") {
  const body = Buffer.from(text);
  response.writeHead(status, {
    "content-type": contentType,
    "content-length": body.byteLength,
    "cache-control": "no-store",
  });
  response.end(body);
}

function isNotFound(error) {
  return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}

function cliPort() {
  const raw = process.env.PORT;
  if (raw === undefined || raw === "") {
    return 8765;
  }
  if (!/^[0-9]+$/.test(raw)) {
    throw new Error(`PORT must be an integer, got ${JSON.stringify(raw)}`);
  }
  const port = Number(raw);
  if (port < 1 || port > 65535) {
    throw new Error(`PORT must be from 1 to 65535, got ${port}`);
  }
  return port;
}

function isDirectRun() {
  const entry = process.argv[1];
  if (entry === undefined) {
    return false;
  }
  return realpathSync(entry) === realpathSync(fileURLToPath(import.meta.url));
}

if (isDirectRun()) {
  const viewer = await startViewer({ port: cliPort(), host: "127.0.0.1" });
  process.stdout.write(`listening ${viewer.url}\n`);
}
