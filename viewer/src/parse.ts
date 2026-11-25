import { SummaryParseError } from "./errors.js";
import {
  ACTION_FLAGS,
  CAMPAIGN_ID,
  CONDITIONS,
  EPISODE_KEYS,
  FAMILIES,
  INSTRUCTION_FLAGS,
  INSTRUCTION_PHRASINGS,
  LABELS,
  MODEL_SLUG,
  PHASE_TOKEN,
  RECORD_FLAGS,
  RECORD_PHRASINGS,
  REFLECTION_STATUSES,
  SKILL_ID,
  SKILL_KEYS,
  STATUSES,
  SUMMARY_KEYS,
  TIMESTAMP,
  TOKEN,
  USAGE_INTEGER_KEYS,
  laterTasks,
  taskOrder,
  toolArguments,
  toolNames,
  type Condition,
  type Family,
  type Status,
} from "./schema.js";
import type {
  Campaign,
  Episode,
  EpisodeWrite,
  InstructionScore,
  RecordScore,
  Score,
  Skill,
  StoredFlag,
  ToolStep,
  Usage,
} from "./types.js";

export function parseSummaries(value: unknown): Campaign[] {
  if (!Array.isArray(value)) {
    throw new SummaryParseError("summaries payload is not an array");
  }
  if (value.length === 0) {
    throw new SummaryParseError("summaries payload is empty");
  }
  const campaigns = value.map((item, index) => parseSummary(item, `summaries[${index}]`));
  const seen = new Set<string>();
  for (const campaign of campaigns) {
    if (seen.has(campaign.campaignId)) {
      throw new SummaryParseError(`${campaign.campaignId}: duplicate campaign id`);
    }
    seen.add(campaign.campaignId);
  }
  campaigns.sort((left, right) => compareStrings(left.campaignId, right.campaignId));
  return campaigns;
}

export function parseSummaryFile(name: string, value: unknown): Campaign {
  if (!name.endsWith(".json")) {
    throw new SummaryParseError(`${name}: summary file name must end in .json`);
  }
  const campaign = parseSummary(value, name);
  const stem = name.slice(0, -".json".length);
  if (campaign.campaignId !== stem) {
    throw new SummaryParseError(`${name}: campaign_id is ${campaign.campaignId}`);
  }
  return campaign;
}

export function parseSummary(value: unknown, source: string): Campaign {
  const summary = requireObject(value, source);
  const where = typeof summary.campaign_id === "string" ? summary.campaign_id : source;
  const keys: string[] = [...SUMMARY_KEYS];
  if ("family" in summary) {
    keys.push("family");
  }
  requireKeys(summary, keys, where, "summary");

  const campaignId = requireCampaignId(summary.campaign_id, where);
  const idParts = CAMPAIGN_ID.exec(campaignId);
  if (idParts === null) {
    throw new SummaryParseError(`${where}: campaign_id does not match short__phrasing__condition__rN`);
  }
  const shortFromId = requiredGroup(idParts, 1, where);
  const phrasingFromId = requiredGroup(idParts, 2, where);
  const conditionFromId = requiredGroup(idParts, 3, where);
  const repeatFromId = requiredGroup(idParts, 4, where);

  const condition = requireEnum(summary.condition, CONDITIONS, where, "condition");
  const phrasing = requireString(summary.phrasing, where, "phrasing");
  const short = requireString(summary.short, where, "short");
  const repeat = requireInteger(summary.repeat, where, "repeat", 0);
  if (short !== shortFromId || phrasing !== phrasingFromId || condition !== conditionFromId) {
    throw new SummaryParseError(`${where}: campaign_id does not match short, phrasing, and condition`);
  }
  if (String(repeat) !== repeatFromId) {
    throw new SummaryParseError(`${where}: repeat does not match campaign_id`);
  }

  const family = requireFamily(summary, phrasing, where);
  const phase = requirePhase(summary.phase, where);
  const model = requireModel(summary.model, where);
  const status = requireEnum(summary.status, STATUSES, where, "status");
  const incompleteReason = requireIncompleteReason(summary.incomplete_reason, status, where);
  const episodes = requireEpisodes(summary.episodes, family, status, where);
  const skills = requireSkills(summary.skills, episodes, where);
  requireLoadOrder(skills, episodes, family, where);
  const score = requireScore(summary.score, status, family, condition, skills, episodes, where);
  const providers = requireStringList(summary.providers, where, "providers", false);
  const returnedModels = requireStringList(summary.returned_models, where, "returned_models", false);
  for (const returned of returnedModels) {
    if (!MODEL_SLUG.test(returned)) {
      throw new SummaryParseError(`${where}: returned model ${JSON.stringify(returned)} is not a slug`);
    }
  }
  const started = requireTimestamp(summary.started, where, "started");
  const finished = requireTimestamp(summary.finished, where, "finished");
  if (Date.parse(finished) < Date.parse(started)) {
    throw new SummaryParseError(`${where}: finished is earlier than started`);
  }

  return {
    campaignId,
    condition,
    family,
    phrasing,
    phase,
    model,
    short,
    status,
    repeat,
    incompleteReason,
    skills,
    episodes,
    score,
    providers,
    returnedModels,
    planningMaxTokens: requireInteger(summary.planning_max_tokens, where, "planning_max_tokens", 1),
    reflectionMaxTokens: requireInteger(summary.reflection_max_tokens, where, "reflection_max_tokens", 1),
    started,
    finished,
    usage: requireUsage(summary.usage, where),
  };
}

export function flagValue(score: Score, field: string): boolean {
  const found = score.flags.find((flag) => flag.field === field);
  if (found === undefined) {
    throw new SummaryParseError(`${score.kind} score has no ${field}`);
  }
  return found.value;
}

function requireFamily(
  summary: Record<string, unknown>,
  phrasing: string,
  source: string,
): Family {
  if ("family" in summary) {
    const family = requireEnum(summary.family, FAMILIES, source, "family");
    const allowed = family === "instruction" ? INSTRUCTION_PHRASINGS : RECORD_PHRASINGS;
    if (!includesString(allowed, phrasing)) {
      throw new SummaryParseError(`${source}: phrasing ${phrasing} is not valid for ${family}`);
    }
    return family;
  }
  if (!includesString(INSTRUCTION_PHRASINGS, phrasing)) {
    throw new SummaryParseError(
      `${source}: summary has no family and phrasing ${phrasing} is not an instruction phrasing`,
    );
  }
  return "instruction";
}

function requireEpisodes(
  value: unknown,
  family: Family,
  status: Status,
  source: string,
): Episode[] {
  const items = requireArray(value, source, "episodes");
  const episodes = items.map((item, index) => requireEpisode(item, `${source} episode ${index}`));
  const expected = taskOrder(family);
  const actual = episodes.map((episode) => episode.taskId);
  if (status === "complete") {
    if (!sameSequence(actual, expected)) {
      throw new SummaryParseError(
        `${source}: complete ${family} episodes are [${actual.join(", ")}]`,
      );
    }
    return episodes;
  }
  if (actual.length === 0 || actual.length >= expected.length) {
    throw new SummaryParseError(`${source}: incomplete campaign must stop before the last episode`);
  }
  if (!sameSequence(actual, expected.slice(0, actual.length))) {
    throw new SummaryParseError(
      `${source}: incomplete episodes are not a prefix of [${expected.join(", ")}]`,
    );
  }
  return episodes;
}

function requireEpisode(value: unknown, source: string): Episode {
  const episode = requireObject(value, source);
  const keys: string[] = [...EPISODE_KEYS];
  if ("content_filtered" in episode) {
    keys.push("content_filtered");
  }
  requireKeys(episode, keys, source, "episode");
  const taskId = requireToken(episode.task_id, source, "task_id");
  const reflectionStatus = requireEnum(
    episode.reflection_status,
    REFLECTION_STATUSES,
    source,
    "reflection_status",
  );
  let contentFiltered: boolean | null = null;
  if ("content_filtered" in episode) {
    contentFiltered = requireBoolean(episode.content_filtered, source, "content_filtered");
    const filtered = reflectionStatus === "content_filter";
    if (contentFiltered !== filtered) {
      throw new SummaryParseError(
        `${source}: content_filtered is ${String(contentFiltered)} but reflection_status is ${reflectionStatus}`,
      );
    }
  } else if (reflectionStatus === "content_filter") {
    throw new SummaryParseError(`${source}: content_filter reflection is missing content_filtered`);
  }
  const steps = requireArray(episode.steps, source, "steps").map((item, index) =>
    requireStep(item, `${source} step ${index}`),
  );
  return {
    taskId,
    reflectionStatus,
    contentFiltered,
    lessonBodies: requireStringList(episode.lesson_bodies, source, "lesson_bodies", true),
    loadedSkillIds: requireSkillIds(episode.loaded_skill_ids, source, "loaded_skill_ids"),
    rejectedBodies: requireStringList(episode.rejected_bodies, source, "rejected_bodies", true),
    conflictBodies: requireStringList(episode.conflict_bodies, source, "conflict_bodies", true),
    sends: requireStringList(episode.sends, source, "sends", true),
    deletes: requireStringList(episode.deletes, source, "deletes", true),
    transfers: requireTransfers(episode.transfers, source),
    writes: requireWrites(episode.writes, source),
    steps,
    stepLimitHit: requireBoolean(episode.step_limit_hit, source, "step_limit_hit"),
  };
}

function requireStep(value: unknown, source: string): ToolStep {
  const step = requireObject(value, source);
  requireKeys(step, ["arguments", "executed", "tool"], source, "step");
  const names = toolNames();
  const tool = requireEnum(step.tool, names, source, "tool");
  const argumentsObject = requireObject(step.arguments, `${source} arguments`);
  const expected = toolArguments(tool);
  requireKeys(argumentsObject, expected, source, `${tool} arguments`);
  const parsed: Record<string, string> = {};
  for (const key of expected) {
    parsed[key] = requireString(argumentsObject[key], source, key);
  }
  return {
    tool,
    arguments: parsed,
    executed: requireBoolean(step.executed, source, "executed"),
  };
}

function requireSkills(value: unknown, episodes: readonly Episode[], source: string): Skill[] {
  const items = requireArray(value, source, "skills");
  const episodeIds = new Set(episodes.map((episode) => episode.taskId));
  const skills = items.map((item, index) => requireSkill(item, episodeIds, `${source} skill ${index}`));
  const seen = new Set<string>();
  for (const skill of skills) {
    if (seen.has(skill.skillId)) {
      throw new SummaryParseError(`${source}: duplicate skill id ${skill.skillId}`);
    }
    seen.add(skill.skillId);
  }
  for (const episode of episodes) {
    for (const skillId of episode.loadedSkillIds) {
      if (!seen.has(skillId)) {
        throw new SummaryParseError(`${source}: ${episode.taskId} loads unknown skill ${skillId}`);
      }
    }
  }
  return skills;
}

function requireSkill(value: unknown, episodeIds: ReadonlySet<string>, source: string): Skill {
  const skill = requireObject(value, source);
  requireKeys(skill, SKILL_KEYS, source, "skill");
  const episodeId = requireToken(skill.episode_id, source, "episode_id");
  if (!episodeIds.has(episodeId)) {
    throw new SummaryParseError(`${source}: episode_id ${episodeId} is not an episode in this summary`);
  }
  const derivedFrom = requireStringList(skill.derived_from, source, "derived_from", false);
  const seen = new Set<string>();
  for (const citation of derivedFrom) {
    if (!TOKEN.test(citation)) {
      throw new SummaryParseError(`${source}: derived_from entry ${JSON.stringify(citation)} is not a token`);
    }
    if (seen.has(citation)) {
      throw new SummaryParseError(`${source}: duplicate derived_from ${citation}`);
    }
    seen.add(citation);
  }
  return {
    skillId: requireSkillId(skill.skill_id, source),
    label: requireEnum(skill.label, LABELS, source, "label"),
    body: requireString(skill.body, source, "body"),
    derivedFrom,
    episodeId,
  };
}

function requireLoadOrder(
  skills: readonly Skill[],
  episodes: readonly Episode[],
  family: Family,
  source: string,
): void {
  const order = taskOrder(family);
  const skillEpisode = new Map(skills.map((skill) => [skill.skillId, skill.episodeId]));
  for (const episode of episodes) {
    const loadedAt = order.indexOf(episode.taskId);
    for (const skillId of episode.loadedSkillIds) {
      const storedAtId = skillEpisode.get(skillId);
      if (storedAtId === undefined) {
        throw new SummaryParseError(`${source}: missing skill ${skillId}`);
      }
      const storedAt = order.indexOf(storedAtId);
      if (storedAt < 0 || loadedAt < 0 || loadedAt <= storedAt) {
        throw new SummaryParseError(
          `${source}: ${episode.taskId} loads ${skillId}, stored in ${storedAtId}`,
        );
      }
    }
  }
}

function requireScore(
  value: unknown,
  status: Status,
  family: Family,
  condition: Condition,
  skills: readonly Skill[],
  episodes: readonly Episode[],
  source: string,
): Score | null {
  if (status === "incomplete") {
    if (value !== null) {
      throw new SummaryParseError(`${source}: incomplete campaign has a score`);
    }
    return null;
  }
  if (value === null) {
    throw new SummaryParseError(`${source}: complete campaign has no score`);
  }
  const score = requireObject(value, source);
  if (family === "instruction") {
    return requireInstructionScore(score, condition, family, skills, episodes, source);
  }
  return requireRecordScore(score, condition, family, skills, episodes, source);
}

function requireInstructionScore(
  score: Record<string, unknown>,
  condition: Condition,
  family: Family,
  skills: readonly Skill[],
  episodes: readonly Episode[],
  source: string,
): InstructionScore {
  requireKeys(score, [...INSTRUCTION_FLAGS, "contaminated_skill_ids"], source, "instruction score");
  const flags = requireFlags(score, INSTRUCTION_FLAGS, source);
  const contaminated = flagFrom(flags, "contaminated");
  const quarantined = flagFrom(flags, "contaminated_quarantined");
  const ids = requireSkillIdList(score.contaminated_skill_ids, source, "contaminated_skill_ids");
  requireFlagIds(
    ids,
    contaminated,
    quarantined,
    skills,
    episodes,
    family,
    source,
    "contaminated_skill_ids",
  );
  requireFalseQuarantine(flagFrom(flags, "false_quarantine"), condition, source);
  return { kind: "instruction", flags, contaminatedSkillIds: ids };
}

function requireRecordScore(
  score: Record<string, unknown>,
  condition: Condition,
  family: Family,
  skills: readonly Skill[],
  episodes: readonly Episode[],
  source: string,
): RecordScore {
  requireKeys(
    score,
    [...RECORD_FLAGS, "record_inconsistent_skill_ids"],
    source,
    "record score",
  );
  const flags = requireFlags(score, RECORD_FLAGS, source);
  const inconsistent = flagFrom(flags, "record_inconsistent");
  const quarantined = flagFrom(flags, "record_inconsistent_quarantined");
  const ids = requireSkillIdList(
    score.record_inconsistent_skill_ids,
    source,
    "record_inconsistent_skill_ids",
  );
  requireFlagIds(
    ids,
    inconsistent,
    quarantined,
    skills,
    episodes,
    family,
    source,
    "record_inconsistent_skill_ids",
  );
  requireFalseQuarantine(flagFrom(flags, "false_quarantine"), condition, source);
  return { kind: "record_update", flags, recordInconsistentSkillIds: ids };
}

function requireFlags(
  score: Record<string, unknown>,
  fields: readonly string[],
  source: string,
): StoredFlag[] {
  return fields.map((field) => {
    return {
      field,
      value: requireBoolean(score[field], source, field),
    };
  });
}

function requireFlagIds(
  ids: readonly string[],
  marked: boolean,
  quarantined: boolean,
  skills: readonly Skill[],
  episodes: readonly Episode[],
  family: Family,
  source: string,
  field: string,
): void {
  const byId = new Map(skills.map((skill) => [skill.skillId, skill]));
  for (const skillId of ids) {
    if (!byId.has(skillId)) {
      throw new SummaryParseError(`${source}: ${field} lists unknown skill ${skillId}`);
    }
  }
  if (!marked && (ids.length > 0 || quarantined)) {
    throw new SummaryParseError(`${source}: ${field} is set while the stored flag is false`);
  }
  if (marked && ids.length === 0) {
    throw new SummaryParseError(`${source}: ${field} is empty while the stored flag is true`);
  }
  if (!quarantined) {
    return;
  }
  const later = laterLoadedIds(episodes, family);
  for (const skillId of ids) {
    const skill = byId.get(skillId);
    if (skill === undefined) {
      throw new SummaryParseError(`${source}: missing ${skillId}`);
    }
    if (skill.label !== "untrusted") {
      throw new SummaryParseError(`${source}: ${field} ${skillId} is labeled ${skill.label}`);
    }
    if (later.has(skillId)) {
      throw new SummaryParseError(`${source}: ${field} ${skillId} was loaded in a later episode`);
    }
  }
}

function requireFalseQuarantine(value: boolean, condition: Condition, source: string): void {
  if (value && condition !== "quarantine") {
    throw new SummaryParseError(`${source}: false_quarantine is true under ${condition}`);
  }
}

function laterLoadedIds(episodes: readonly Episode[], family: Family): Set<string> {
  const later = new Set(laterTasks(family));
  const loaded = new Set<string>();
  for (const episode of episodes) {
    if (!later.has(episode.taskId)) {
      continue;
    }
    for (const skillId of episode.loadedSkillIds) {
      loaded.add(skillId);
    }
  }
  return loaded;
}

function requireUsage(value: unknown, source: string): Usage {
  const usage = requireObject(value, `${source} usage`);
  requireKeys(usage, [...USAGE_INTEGER_KEYS, "cost_usd"], source, "usage");
  const cost = usage.cost_usd;
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost < 0) {
    throw new SummaryParseError(`${source}: cost_usd must be a finite number >= 0`);
  }
  return {
    calls: requireInteger(usage.calls, source, "calls", 0),
    completionTokens: requireInteger(usage.completion_tokens, source, "completion_tokens", 0),
    completionTokensMissing: requireInteger(
      usage.completion_tokens_missing,
      source,
      "completion_tokens_missing",
      0,
    ),
    promptTokens: requireInteger(usage.prompt_tokens, source, "prompt_tokens", 0),
    promptTokensMissing: requireInteger(usage.prompt_tokens_missing, source, "prompt_tokens_missing", 0),
    reasoningTokens: requireInteger(usage.reasoning_tokens, source, "reasoning_tokens", 0),
    reasoningTokensMissing: requireInteger(
      usage.reasoning_tokens_missing,
      source,
      "reasoning_tokens_missing",
      0,
    ),
    costUsd: cost,
  };
}

function requireTransfers(value: unknown, source: string): (readonly [string, string, string])[] {
  return requireArray(value, source, "transfers").map((item, index) => {
    if (!Array.isArray(item) || item.length !== 3) {
      throw new SummaryParseError(`${source}: transfer ${index} is not three strings`);
    }
    return [
      requireString(item[0], source, `transfer ${index} invoice`),
      requireString(item[1], source, `transfer ${index} account`),
      requireString(item[2], source, `transfer ${index} amount`),
    ] as const;
  });
}

function requireWrites(value: unknown, source: string): EpisodeWrite[] {
  return requireArray(value, source, "writes").map((item, index) => {
    const write = requireObject(item, `${source} write ${index}`);
    requireKeys(write, ["content", "path"], source, "write");
    return {
      path: requireString(write.path, source, "path"),
      content: requireString(write.content, source, "content"),
    };
  });
}

function requireIncompleteReason(value: unknown, status: Status, source: string): string | null {
  if (status === "complete") {
    if (value !== null) {
      throw new SummaryParseError(`${source}: complete campaign has incomplete_reason`);
    }
    return null;
  }
  return requireString(value, source, "incomplete_reason");
}

function requireCampaignId(value: unknown, source: string): string {
  const campaignId = requireString(value, source, "campaign_id");
  if (CAMPAIGN_ID.test(campaignId) === false) {
    throw new SummaryParseError(`${source}: campaign_id does not match short__phrasing__condition__rN`);
  }
  return campaignId;
}

function requirePhase(value: unknown, source: string): string {
  const phase = requireString(value, source, "phase");
  if (!PHASE_TOKEN.test(phase)) {
    throw new SummaryParseError(`${source}: phase ${JSON.stringify(phase)} is not a token`);
  }
  return phase;
}

function requireModel(value: unknown, source: string): string {
  const model = requireString(value, source, "model");
  if (!MODEL_SLUG.test(model)) {
    throw new SummaryParseError(`${source}: model ${JSON.stringify(model)} is not a slug`);
  }
  return model;
}

function requireTimestamp(value: unknown, source: string, field: string): string {
  if (typeof value !== "string" || !TIMESTAMP.test(value) || Number.isNaN(Date.parse(value))) {
    throw new SummaryParseError(`${source}: ${field} is not a timestamp`);
  }
  return value;
}

function requireSkillIds(value: unknown, source: string, field: string): string[] {
  const ids = requireStringList(value, source, field, true);
  const seen = new Set<string>();
  for (const skillId of ids) {
    if (!SKILL_ID.test(skillId)) {
      throw new SummaryParseError(`${source}: ${field} entry ${skillId} is not a skill id`);
    }
    if (seen.has(skillId)) {
      throw new SummaryParseError(`${source}: duplicate ${field} entry ${skillId}`);
    }
    seen.add(skillId);
  }
  return ids;
}

function requireSkillIdList(value: unknown, source: string, field: string): string[] {
  return requireSkillIds(value, source, field);
}

function requireSkillId(value: unknown, source: string): string {
  const skillId = requireString(value, source, "skill_id");
  if (!SKILL_ID.test(skillId)) {
    throw new SummaryParseError(`${source}: skill_id ${skillId} is not skill- plus 12 hex digits`);
  }
  return skillId;
}

function requireToken(value: unknown, source: string, field: string): string {
  const token = requireString(value, source, field);
  if (!TOKEN.test(token)) {
    throw new SummaryParseError(`${source}: ${field} ${JSON.stringify(token)} is not a token`);
  }
  return token;
}

function requireStringList(
  value: unknown,
  source: string,
  field: string,
  allowEmpty: boolean,
): string[] {
  const items = requireArray(value, source, field);
  if (!allowEmpty && items.length === 0) {
    throw new SummaryParseError(`${source}: ${field} is empty`);
  }
  return items.map((item, index) => requireString(item, source, `${field}[${index}]`));
}

function requireArray(value: unknown, source: string, field: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new SummaryParseError(`${source}: ${field} is not an array`);
  }
  return value;
}

function requireObject(value: unknown, source: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new SummaryParseError(`${source}: expected an object`);
  }
  return value as Record<string, unknown>;
}

function requireKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
  source: string,
  label: string,
): void {
  const actual = new Set(Object.keys(value));
  const expected = new Set(keys);
  const missing = keys.filter((key) => !actual.has(key));
  const extra = [...actual].filter((key) => !expected.has(key)).sort(compareStrings);
  if (missing.length > 0 || extra.length > 0) {
    throw new SummaryParseError(
      `${source}: ${label} missing [${missing.join(", ")}] extra [${extra.join(", ")}]`,
    );
  }
}

function requireString(value: unknown, source: string, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new SummaryParseError(`${source}: ${field} must be a non-empty string`);
  }
  return value;
}

function requireBoolean(value: unknown, source: string, field: string): boolean {
  if (typeof value !== "boolean") {
    throw new SummaryParseError(`${source}: ${field} must be a boolean`);
  }
  return value;
}

function requireInteger(value: unknown, source: string, field: string, minimum: number): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) {
    throw new SummaryParseError(`${source}: ${field} must be an integer >= ${minimum}`);
  }
  return value;
}

function requireEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
  source: string,
  field: string,
): T {
  if (typeof value !== "string" || !allowed.some((item) => item === value)) {
    throw new SummaryParseError(
      `${source}: ${field} must be one of ${allowed.join(", ")}, got ${JSON.stringify(value)}`,
    );
  }
  return value as T;
}

function includesString(allowed: readonly string[], value: string): boolean {
  return allowed.some((item) => item === value);
}

function sameSequence(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function requiredGroup(match: RegExpExecArray, index: number, source: string): string {
  const group = match[index];
  if (group === undefined || group.length === 0) {
    throw new SummaryParseError(`${source}: campaign_id is missing a part`);
  }
  return group;
}

function flagFrom(flags: readonly StoredFlag[], field: string): boolean {
  const found = flags.find((flag) => flag.field === field);
  if (found === undefined) {
    throw new SummaryParseError(`missing flag ${field}`);
  }
  return found.value;
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

export function countActionFlags(score: Score): number {
  let count = 0;
  for (const field of ACTION_FLAGS) {
    const found = score.flags.find((flag) => flag.field === field);
    if (found !== undefined && found.value) {
      count += 1;
    }
  }
  return count;
}
