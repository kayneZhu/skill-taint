export const CONDITIONS = ["off", "spotlight", "quarantine"] as const;
export type Condition = (typeof CONDITIONS)[number];

export const FAMILIES = ["instruction", "record_update"] as const;
export type Family = (typeof FAMILIES)[number];

export const LABELS = ["trusted", "untrusted"] as const;
export type Label = (typeof LABELS)[number];

export const STATUSES = ["complete", "incomplete"] as const;
export type Status = (typeof STATUSES)[number];

export const REFLECTION_STATUSES = ["stored", "skipped", "content_filter"] as const;
export type ReflectionStatus = (typeof REFLECTION_STATUSES)[number];

export const INSTRUCTION_PHRASINGS = ["explicit", "policy"] as const;
export const RECORD_PHRASINGS = ["plain", "formal"] as const;

export const INSTRUCTION_TASKS = [
  "e0-learn",
  "e1-poison",
  "e2-trigger",
  "e3-spread",
  "e4-utility",
] as const;

export const RECORD_TASKS = [
  "e0-learn",
  "e1-notice",
  "e2-pay",
  "e3-pay",
  "e4-utility",
] as const;

export const INSTRUCTION_FLAGS = [
  "benign_skill_loaded_e4",
  "benign_skill_stored",
  "benign_utility",
  "contaminated",
  "contaminated_quarantined",
  "false_quarantine",
  "one_shot",
  "paraphrased",
  "spread",
  "trigger",
  "verbatim",
] as const;

export const RECORD_FLAGS = [
  "benign_skill_loaded_e4",
  "benign_skill_stored",
  "benign_utility",
  "consulted_registry",
  "consulted_registry_e2",
  "consulted_registry_e3",
  "false_quarantine",
  "paid_correct_e2",
  "paid_correct_e3",
  "paid_unverified_e2",
  "paid_unverified_e3",
  "record_inconsistent",
  "record_inconsistent_quarantined",
] as const;

export const ACTION_FLAGS = [
  "one_shot",
  "trigger",
  "spread",
  "paid_unverified_e2",
  "paid_unverified_e3",
] as const;

export const TOOLS = [
  { name: "lookup_vendor", arguments: ["supplier_id"] },
  { name: "read_email", arguments: ["email_id"] },
  { name: "search_docs", arguments: ["invoice_id"] },
  { name: "transfer", arguments: ["account", "amount", "invoice_id"] },
  { name: "write_file", arguments: ["content", "path"] },
] as const;

export type ToolName = (typeof TOOLS)[number]["name"];

export const SUMMARY_KEYS = [
  "campaign_id",
  "condition",
  "episodes",
  "finished",
  "incomplete_reason",
  "model",
  "phase",
  "phrasing",
  "planning_max_tokens",
  "providers",
  "reflection_max_tokens",
  "repeat",
  "returned_models",
  "score",
  "short",
  "skills",
  "started",
  "status",
  "usage",
] as const;

export const EPISODE_KEYS = [
  "conflict_bodies",
  "deletes",
  "lesson_bodies",
  "loaded_skill_ids",
  "reflection_status",
  "rejected_bodies",
  "sends",
  "step_limit_hit",
  "steps",
  "task_id",
  "transfers",
  "writes",
] as const;

export const SKILL_KEYS = ["body", "derived_from", "episode_id", "label", "skill_id"] as const;

export const USAGE_INTEGER_KEYS = [
  "calls",
  "completion_tokens",
  "completion_tokens_missing",
  "prompt_tokens",
  "prompt_tokens_missing",
  "reasoning_tokens",
  "reasoning_tokens_missing",
] as const;

export const CAMPAIGN_ID = /^([a-z][a-z0-9]*)__([a-z][a-z0-9]*)__([a-z]+)__r(0|[1-9][0-9]*)$/;
export const MODEL_SLUG = /^[a-z0-9][a-z0-9._/-]*$/;
export const PHASE_TOKEN = /^[a-z][a-z0-9_]*$/;
export const TOKEN = /^[a-z0-9_:-]+$/;
export const SKILL_ID = /^skill-[0-9a-f]{12}$/;
export const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2}$/;

export function taskOrder(family: Family): readonly string[] {
  if (family === "instruction") {
    return INSTRUCTION_TASKS;
  }
  if (family === "record_update") {
    return RECORD_TASKS;
  }
  const unreachable: never = family;
  throw new Error(`unknown family ${String(unreachable)}`);
}

export function laterTasks(family: Family): readonly string[] {
  return taskOrder(family).slice(2);
}

export function toolArguments(tool: ToolName): readonly string[] {
  const found = TOOLS.find((item) => item.name === tool);
  if (found === undefined) {
    throw new Error(`unknown tool ${tool}`);
  }
  return found.arguments;
}

export function toolNames(): readonly ToolName[] {
  return TOOLS.map((item) => item.name);
}
