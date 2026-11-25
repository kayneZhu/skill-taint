import { parseSummaries } from "./parse.js";
import { mountApp, renderFatal } from "./render.js";

const root = document.querySelector("#app");
if (!(root instanceof HTMLElement)) {
  throw new Error("missing #app");
}

try {
  const response = await fetch("/api/summaries");
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`GET /api/summaries failed (${response.status}): ${detail}`);
  }
  const payload: unknown = await response.json();
  mountApp(root, parseSummaries(payload));
} catch (error) {
  renderFatal(root, error);
  throw error;
}
