import { ChannelError } from "./errors.js";
import { laterTasks, taskOrder } from "./schema.js";
import type { Campaign, Skill } from "./types.js";

export type ChannelDecision =
  | { kind: "omitted-untrusted" }
  | { kind: "loaded-despite-untrusted"; episodes: readonly string[] }
  | { kind: "loaded"; episodes: readonly string[] }
  | { kind: "not-loaded" };

export interface SkillChannel {
  skillId: string;
  label: Skill["label"];
  loadedIn: readonly string[];
  decision: ChannelDecision;
}

export function skillChannels(campaign: Campaign): SkillChannel[] {
  const order = taskOrder(campaign.family);
  const later = new Set(laterTasks(campaign.family));
  return campaign.skills.map((skill) => {
    const storedAt = order.indexOf(skill.episodeId);
    if (storedAt < 0) {
      throw new ChannelError(`${campaign.campaignId}: ${skill.skillId} episode ${skill.episodeId} is unknown`);
    }
    const loadedIn: string[] = [];
    for (const episode of campaign.episodes) {
      if (!episode.loadedSkillIds.includes(skill.skillId)) {
        continue;
      }
      const loadedAt = order.indexOf(episode.taskId);
      if (loadedAt < 0 || loadedAt <= storedAt) {
        throw new ChannelError(
          `${campaign.campaignId}: ${episode.taskId} loads ${skill.skillId}, stored in ${skill.episodeId}`,
        );
      }
      loadedIn.push(episode.taskId);
    }
    const loadedLater = loadedIn.filter((taskId) => later.has(taskId));
    if (campaign.condition === "quarantine" && skill.label === "untrusted") {
      if (loadedLater.length > 0) {
        return {
          skillId: skill.skillId,
          label: skill.label,
          loadedIn,
          decision: { kind: "loaded-despite-untrusted", episodes: loadedLater },
        };
      }
      return {
        skillId: skill.skillId,
        label: skill.label,
        loadedIn,
        decision: { kind: "omitted-untrusted" },
      };
    }
    if (loadedLater.length > 0) {
      return {
        skillId: skill.skillId,
        label: skill.label,
        loadedIn,
        decision: { kind: "loaded", episodes: loadedLater },
      };
    }
    return {
      skillId: skill.skillId,
      label: skill.label,
      loadedIn,
      decision: { kind: "not-loaded" },
    };
  });
}
