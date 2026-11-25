import { skillChannels } from "./channel.js";
import { COPY, decisionText, familyLabel, fieldNote } from "./copy.js";
import { filterCampaigns, uniqueShorts } from "./filter.js";
import { overview as campaignOverview } from "./overview.js";
import { CONDITIONS, FAMILIES, STATUSES } from "./schema.js";
import type { Campaign, CampaignQuery, Episode, Score, Skill } from "./types.js";

interface ViewState extends CampaignQuery {
  selectedId: string;
}

export function renderFatal(root: HTMLElement, error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  document.title = COPY.loadErrorTitle;
  root.replaceChildren(h("h1", null, [COPY.loadErrorTitle]), h("pre", "error", [message]));
}

export function mountApp(root: HTMLElement, campaigns: readonly Campaign[]): void {
  if (campaigns.length === 0) {
    throw new Error("mountApp requires at least one campaign");
  }
  const byId = new Map(campaigns.map((campaign) => [campaign.campaignId, campaign]));
  const state: ViewState = {
    text: "",
    short: "all",
    family: "all",
    condition: "all",
    status: "all",
    untrustedOnly: false,
    lenientOnly: false,
    selectedId: initialId(byId),
  };
  const stats = campaignOverview(campaigns);

  root.replaceChildren();
  document.title = COPY.pageTitle;
  root.append(
    h("header", "banner", [
      h("div", "banner-mark", [h("span", "mark mark-t", ["T"]), h("span", "mark mark-u", ["U"])]),
      h("div", null, [
        h("p", "eyebrow", ["skill-taint"]),
        h("h1", null, [COPY.pageTitle]),
        h("p", "intro", [COPY.intro]),
        reportLink(),
      ]),
    ]),
  );

  const counts = h("section", "counts", [h("h2", "visually-hidden", ["Counts from the summary files"])]);
  for (const row of COPY.overview) {
    counts.append(
      h("article", "count", [
        h("p", "count-value", [String(stats[row.key])]),
        h("h3", null, [row.label]),
        h("p", "count-note", [row.note]),
      ]),
    );
  }
  root.append(counts);

  const search = document.createElement("input");
  search.type = "search";
  search.id = "campaign-search";
  search.autocomplete = "off";
  search.spellcheck = false;
  const model = selectControl("model-filter", uniqueShorts(campaigns), (value) => value);
  const family = selectControl("family-filter", FAMILIES, (value) => familyLabel(value));
  const condition = selectControl("condition-filter", CONDITIONS, (value) => value);
  const status = selectControl("status-filter", STATUSES, (value) => value);
  const untrustedOnly = checkboxControl("untrusted-only");
  const lenientOnly = checkboxControl("lenient-only");

  const filters = h("form", "filters", [
    h("h2", null, [COPY.filters]),
    labeled(COPY.searchLabel, search),
    labeled(COPY.modelLabel, model),
    labeled(COPY.familyLabel, family),
    labeled(COPY.conditionLabel, condition),
    labeled(COPY.statusLabel, status),
    labeledCheck(COPY.untrustedOnly, untrustedOnly),
    labeledCheck(COPY.lenientOnly, lenientOnly),
  ]);
  filters.addEventListener("submit", (event) => {
    event.preventDefault();
  });

  const list = h("div", "campaign-list", []);
  const listCount = h("p", "list-count", []);
  const detail = h("div", "detail", []);
  const workspace = h("div", "workspace", [
    h("aside", null, [filters, listCount, list]),
    h("main", null, [detail]),
  ]);
  root.append(workspace);

  const refresh = (): void => {
    const shown = filterCampaigns(campaigns, state);
    fillList(list, listCount, shown, campaigns.length, state.selectedId, (campaignId) => {
      state.selectedId = campaignId;
      writeHash(campaignId, "push");
      refresh();
    });
    const selected = byId.get(state.selectedId);
    if (selected === undefined) {
      throw new Error(`selected campaign is not loaded: ${state.selectedId}`);
    }
    const visible = shown.some((campaign) => campaign.campaignId === selected.campaignId);
    fillDetail(detail, selected, visible);
  };

  search.addEventListener("input", () => {
    state.text = search.value;
    refresh();
  });
  model.addEventListener("change", () => {
    state.short = model.value;
    refresh();
  });
  family.addEventListener("change", () => {
    state.family = requireChoice(family.value, FAMILIES, "all");
    refresh();
  });
  condition.addEventListener("change", () => {
    state.condition = requireChoice(condition.value, CONDITIONS, "all");
    refresh();
  });
  status.addEventListener("change", () => {
    state.status = requireChoice(status.value, STATUSES, "all");
    refresh();
  });
  untrustedOnly.addEventListener("change", () => {
    state.untrustedOnly = untrustedOnly.checked;
    refresh();
  });
  lenientOnly.addEventListener("change", () => {
    state.lenientOnly = lenientOnly.checked;
    refresh();
  });

  const applyHash = (): void => {
    try {
      const hash = readHash();
      if (hash === null) {
        return;
      }
      if (!byId.has(hash)) {
        throw new Error(`URL hash does not name a campaign: ${hash}`);
      }
      state.selectedId = hash;
      refresh();
    } catch (error) {
      renderFatal(root, error);
    }
  };
  window.addEventListener("hashchange", applyHash);
  window.addEventListener("popstate", applyHash);
  refresh();
}

function initialId(byId: ReadonlyMap<string, Campaign>): string {
  const hash = readHash();
  if (hash === null) {
    const first = [...byId.keys()].sort((left, right) => compareStrings(left, right))[0];
    if (first === undefined) {
      throw new Error("no campaigns");
    }
    writeHash(first, "replace");
    return first;
  }
  if (!byId.has(hash)) {
    throw new Error(`URL hash does not name a campaign: ${hash}`);
  }
  return hash;
}

function fillList(
  list: HTMLElement,
  listCount: HTMLElement,
  shown: readonly Campaign[],
  total: number,
  selectedId: string,
  onSelect: (campaignId: string) => void,
): void {
  listCount.replaceChildren(document.createTextNode(`${shown.length} of ${total}`));
  list.replaceChildren();
  if (shown.length === 0) {
    list.append(h("p", "empty", [COPY.noMatches]));
    return;
  }
  for (const campaign of shown) {
    const trusted = campaign.skills.filter((skill) => skill.label === "trusted").length;
    const untrusted = campaign.skills.length - trusted;
    const chips = [
      h("span", "chip", [campaign.short]),
      h("span", "chip", [campaign.condition]),
      h("span", "chip", [campaign.status]),
      h("span", "chip chip-t", [`T ${trusted}`]),
      h("span", "chip chip-u", [`U ${untrusted}`]),
    ];
    if (hasLenientFlag(campaign)) {
      chips.push(h("span", "chip chip-flag", ["lenient flag"]));
    }
    const item = h("button", "campaign", [
      h("span", "campaign-id", [campaign.campaignId]),
      h("span", "chips", chips),
    ]);
    item.type = "button";
    if (campaign.campaignId === selectedId) {
      item.classList.add("is-selected");
      item.setAttribute("aria-current", "true");
    }
    item.addEventListener("click", () => {
      onSelect(campaign.campaignId);
    });
    list.append(item);
  }
}

function fillDetail(detail: HTMLElement, campaign: Campaign, visible: boolean): void {
  const channels = skillChannels(campaign);
  const channelById = new Map(channels.map((channel) => [channel.skillId, channel]));
  detail.replaceChildren();
  if (!visible) {
    detail.append(h("p", "notice", [COPY.hiddenByFilters]));
  }
  detail.append(
    h("h2", null, [campaign.campaignId]),
    metaList(campaign),
    h("section", null, [
      h("h3", null, [COPY.quarantineHeading]),
      h("p", null, [campaign.condition === "quarantine" ? COPY.quarantineRule : COPY.otherRule]),
    ]),
    h("section", null, [h("h3", null, [COPY.skillsHeading]), ...campaign.skills.map((skill) => skillCard(skill, channelById))]),
    h("section", null, [h("h3", null, [COPY.episodesHeading]), ...campaign.episodes.map((episode) => episodeCard(episode))]),
    h("section", null, [h("h3", null, [COPY.scoreHeading]), scoreBlock(campaign.score)]),
  );
}

function metaList(campaign: Campaign): HTMLDListElement {
  const rows: readonly (readonly [string, string])[] = [
    ["Family", `${familyLabel(campaign.family)} (${campaign.family})`],
    ["Phrasing", campaign.phrasing],
    ["Phase", campaign.phase],
    ["Condition", campaign.condition],
    ["Status", campaign.status],
    ["Model", campaign.model],
    ["Short name", campaign.short],
    ["Repeat", String(campaign.repeat)],
    [COPY.providers, campaign.providers.join(", ")],
    [COPY.returnedModels, campaign.returnedModels.join(", ")],
    ["Planning max tokens", String(campaign.planningMaxTokens)],
    ["Reflection max tokens", String(campaign.reflectionMaxTokens)],
    ["Started", campaign.started],
    ["Finished", campaign.finished],
    ["Calls", String(campaign.usage.calls)],
    ["Prompt tokens", formatInteger(campaign.usage.promptTokens)],
    ["Completion tokens", formatInteger(campaign.usage.completionTokens)],
    ["Reasoning tokens", formatInteger(campaign.usage.reasoningTokens)],
    ["Cost USD", String(campaign.usage.costUsd)],
  ];
  const list = h("dl", "meta", []);
  for (const [term, value] of rows) {
    list.append(h("dt", null, [term]), h("dd", null, [value]));
  }
  if (campaign.incompleteReason !== null) {
    list.append(h("dt", null, [COPY.incompleteReason]), h("dd", null, [campaign.incompleteReason]));
  }
  return list;
}

function skillCard(
  skill: Skill,
  channelById: ReadonlyMap<string, ReturnType<typeof skillChannels>[number]>,
): HTMLElement {
  const channel = channelById.get(skill.skillId);
  if (channel === undefined) {
    throw new Error(`missing channel for ${skill.skillId}`);
  }
  const badgeClass = skill.label === "trusted" ? "badge badge-t" : "badge badge-u";
  const badgeText = skill.label === "trusted" ? "T trusted" : "U untrusted";
  const mismatch = channel.decision.kind === "loaded-despite-untrusted" ? " skill-mismatch" : "";
  return h("article", `skill${mismatch}`, [
    h("div", "skill-head", [
      h("span", badgeClass, [badgeText]),
      h("code", null, [skill.skillId]),
    ]),
    h("p", "decision", [decisionText(channel.decision)]),
    h("p", "skill-meta", [`${COPY.episode}: ${skill.episodeId}`]),
    h("p", "skill-meta", [`${COPY.derivedFrom}: ${skill.derivedFrom.join(", ")}`]),
    h("p", "skill-meta", [`${COPY.loadedIn}: ${channel.loadedIn.length === 0 ? COPY.none : channel.loadedIn.join(", ")}`]),
    h("pre", "body", [skill.body]),
  ]);
}

function episodeCard(episode: Episode): HTMLElement {
  const details = document.createElement("details");
  details.className = "episode";
  if (episode.taskId === "e1-poison" || episode.taskId === "e1-notice") {
    details.open = true;
  }
  const contentFiltered =
    episode.contentFiltered === null ? COPY.notRecorded : String(episode.contentFiltered);
  details.append(
    h("summary", null, [
      `${episode.taskId} · ${episode.reflectionStatus} · ${episode.steps.length} steps`,
    ]),
    h("p", null, [COPY.reflectionGloss[episode.reflectionStatus]]),
    h("p", null, [`${COPY.contentFiltered}: ${contentFiltered}`]),
    h("p", null, [`${COPY.stepLimit}: ${String(episode.stepLimitHit)}`]),
    stringBlock(COPY.lessons, episode.lessonBodies),
    stringBlock(COPY.rejected, episode.rejectedBodies),
    stringBlock(COPY.conflicts, episode.conflictBodies),
    stringBlock(COPY.sends, episode.sends),
    stringBlock(COPY.deletes, episode.deletes),
    transferBlock(episode),
    writeBlock(episode),
    stepBlock(episode),
  );
  return details;
}

function scoreBlock(score: Score | null): HTMLElement {
  if (score === null) {
    return h("p", null, [COPY.noScore]);
  }
  const intro = score.kind === "instruction" ? COPY.scoreIntro.instruction : COPY.scoreIntro.record_update;
  const table = document.createElement("table");
  table.className = "score";
  const head = h("tr", null, [h("th", null, [COPY.field]), h("th", null, [COPY.value]), h("th", null, [COPY.meaning])]);
  table.append(h("thead", null, [head]));
  const body = document.createElement("tbody");
  for (const flag of score.flags) {
    body.append(
      h("tr", null, [
        h("td", null, [h("code", null, [flag.field])]),
        h("td", null, [String(flag.value)]),
        h("td", null, [fieldNote(flag.field)]),
      ]),
    );
  }
  table.append(body);
  const ids = score.kind === "instruction" ? score.contaminatedSkillIds : score.recordInconsistentSkillIds;
  const idField = score.kind === "instruction" ? "contaminated_skill_ids" : "record_inconsistent_skill_ids";
  return h("div", null, [
    h("p", null, [intro]),
    table,
    h("p", null, [
      `${idField}: ${ids.length === 0 ? COPY.none : ids.join(", ")}. ${COPY.idFields[idField]}`,
    ]),
  ]);
}

function stringBlock(title: string, values: readonly string[]): HTMLElement {
  const block = h("div", "block", [h("h4", null, [title])]);
  if (values.length === 0) {
    block.append(h("p", null, [COPY.none]));
    return block;
  }
  for (const value of values) {
    block.append(h("pre", "body", [value]));
  }
  return block;
}

function transferBlock(episode: Episode): HTMLElement {
  const block = h("div", "block", [h("h4", null, [COPY.transfers])]);
  if (episode.transfers.length === 0) {
    block.append(h("p", null, [COPY.none]));
    return block;
  }
  for (const transfer of episode.transfers) {
    block.append(h("p", null, [`${transfer[0]} → ${transfer[1]} · ${transfer[2]}`]));
  }
  return block;
}

function writeBlock(episode: Episode): HTMLElement {
  const block = h("div", "block", [h("h4", null, [COPY.writes])]);
  if (episode.writes.length === 0) {
    block.append(h("p", null, [COPY.none]));
    return block;
  }
  for (const write of episode.writes) {
    block.append(h("p", "skill-meta", [write.path]), h("pre", "body", [write.content]));
  }
  return block;
}

function stepBlock(episode: Episode): HTMLElement {
  const block = h("div", "block", [h("h4", null, [COPY.steps])]);
  if (episode.steps.length === 0) {
    block.append(h("p", null, [COPY.none]));
    return block;
  }
  for (const step of episode.steps) {
    const args = h("dl", "args", []);
    for (const key of Object.keys(step.arguments).sort(compareStrings)) {
      const value = step.arguments[key];
      if (value === undefined) {
        throw new Error(`missing argument ${key}`);
      }
      args.append(h("dt", null, [key]), h("dd", null, [value]));
    }
    block.append(
      h("div", "step", [
        h("p", "step-title", [
          `${step.tool} · ${step.executed ? COPY.executed : COPY.notExecuted}`,
        ]),
        args,
      ]),
    );
  }
  return block;
}

function reportLink(): HTMLElement {
  const link = h("a", null, [`${COPY.reportLink} (${COPY.reportPath})`]);
  link.href = COPY.reportHref;
  link.rel = "noreferrer";
  return h("p", null, [link]);
}

function labeled(text: string, control: HTMLElement): HTMLElement {
  const id = control.id;
  if (id.length === 0) {
    throw new Error("filter control is missing an id");
  }
  const label = h("label", null, [text]);
  label.htmlFor = id;
  return h("div", "field", [label, control]);
}

function labeledCheck(text: string, control: HTMLInputElement): HTMLElement {
  const label = h("label", "check", [control, document.createTextNode(text)]);
  return h("div", "field", [label]);
}

function selectControl<T extends string>(
  id: string,
  values: readonly T[],
  labelFor: (value: T) => string,
): HTMLSelectElement {
  const select = document.createElement("select");
  select.id = id;
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = COPY.all;
  select.append(all);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labelFor(value);
    select.append(option);
  }
  return select;
}

function checkboxControl(id: string): HTMLInputElement {
  const input = document.createElement("input");
  input.type = "checkbox";
  input.id = id;
  return input;
}

function requireChoice<T extends string>(value: string, allowed: readonly T[], all: "all"): T | "all" {
  if (value === all) {
    return all;
  }
  const found = allowed.find((item) => item === value);
  if (found === undefined) {
    throw new Error(`unknown filter value ${value}`);
  }
  return found;
}

function hasLenientFlag(campaign: Campaign): boolean {
  if (campaign.score === null || campaign.score.kind !== "instruction") {
    return false;
  }
  const flag = campaign.score.flags.find((item) => item.field === "contaminated");
  if (flag === undefined) {
    throw new Error(`${campaign.campaignId}: instruction score has no contaminated flag`);
  }
  return flag.value;
}

function formatInteger(value: number): string {
  if (!Number.isInteger(value)) {
    throw new Error(`expected an integer, got ${value}`);
  }
  return new Intl.NumberFormat("en-US").format(value);
}

function readHash(): string | null {
  const raw = location.hash.startsWith("#") ? location.hash.slice(1) : "";
  if (raw.length === 0) {
    return null;
  }
  try {
    return decodeURIComponent(raw);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`URL hash is not valid percent-encoding: ${message}`);
  }
}

function writeHash(campaignId: string, mode: "push" | "replace"): void {
  const next = `#${encodeURIComponent(campaignId)}`;
  if (location.hash === next) {
    return;
  }
  if (mode === "push") {
    history.pushState(null, "", next);
    return;
  }
  history.replaceState(null, "", next);
}

function compareStrings(left: string, right: string): number {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
}

function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string | null,
  children: readonly (Node | string)[],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className !== null) {
    node.className = className;
  }
  for (const child of children) {
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}
