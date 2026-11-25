import type {
  Condition,
  Family,
  Label,
  ReflectionStatus,
  Status,
  ToolName,
} from "./schema.js";

export interface ToolStep {
  tool: ToolName;
  arguments: Readonly<Record<string, string>>;
  executed: boolean;
}

export interface EpisodeWrite {
  path: string;
  content: string;
}

export interface Episode {
  taskId: string;
  reflectionStatus: ReflectionStatus;
  contentFiltered: boolean | null;
  lessonBodies: readonly string[];
  loadedSkillIds: readonly string[];
  rejectedBodies: readonly string[];
  conflictBodies: readonly string[];
  sends: readonly string[];
  deletes: readonly string[];
  transfers: readonly (readonly [string, string, string])[];
  writes: readonly EpisodeWrite[];
  steps: readonly ToolStep[];
  stepLimitHit: boolean;
}

export interface Skill {
  skillId: string;
  label: Label;
  body: string;
  derivedFrom: readonly string[];
  episodeId: string;
}

export interface StoredFlag {
  field: string;
  value: boolean;
}

export interface InstructionScore {
  kind: "instruction";
  flags: readonly StoredFlag[];
  contaminatedSkillIds: readonly string[];
}

export interface RecordScore {
  kind: "record_update";
  flags: readonly StoredFlag[];
  recordInconsistentSkillIds: readonly string[];
}

export type Score = InstructionScore | RecordScore;

export interface Usage {
  calls: number;
  completionTokens: number;
  completionTokensMissing: number;
  promptTokens: number;
  promptTokensMissing: number;
  reasoningTokens: number;
  reasoningTokensMissing: number;
  costUsd: number;
}

export interface Campaign {
  campaignId: string;
  condition: Condition;
  family: Family;
  phrasing: string;
  phase: string;
  model: string;
  short: string;
  status: Status;
  repeat: number;
  incompleteReason: string | null;
  skills: readonly Skill[];
  episodes: readonly Episode[];
  score: Score | null;
  providers: readonly string[];
  returnedModels: readonly string[];
  planningMaxTokens: number;
  reflectionMaxTokens: number;
  started: string;
  finished: string;
  usage: Usage;
}

export interface Overview {
  campaigns: number;
  complete: number;
  incomplete: number;
  trustedSkills: number;
  untrustedSkills: number;
  falseQuarantine: number;
  lenientContamination: number;
  recordInconsistent: number;
  laterActionFlags: number;
  untrustedLoadedLater: number;
}

export interface CampaignQuery {
  text: string;
  short: string;
  family: Family | "all";
  condition: Condition | "all";
  status: Status | "all";
  untrustedOnly: boolean;
  lenientOnly: boolean;
}
