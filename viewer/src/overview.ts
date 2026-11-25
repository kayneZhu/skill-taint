import { skillChannels } from "./channel.js";
import { countActionFlags, flagValue } from "./parse.js";
import type { Campaign, Overview } from "./types.js";

export function overview(campaigns: readonly Campaign[]): Overview {
  if (campaigns.length === 0) {
    throw new Error("overview requires at least one campaign");
  }
  let complete = 0;
  let incomplete = 0;
  let trustedSkills = 0;
  let untrustedSkills = 0;
  let falseQuarantine = 0;
  let lenientContamination = 0;
  let recordInconsistent = 0;
  let laterActionFlags = 0;
  let untrustedLoadedLater = 0;
  for (const campaign of campaigns) {
    if (campaign.status === "complete") {
      complete += 1;
    } else {
      incomplete += 1;
    }
    for (const skill of campaign.skills) {
      if (skill.label === "trusted") {
        trustedSkills += 1;
      } else if (skill.label === "untrusted") {
        untrustedSkills += 1;
      } else {
        const unreachable: never = skill.label;
        throw new Error(`${campaign.campaignId}: unknown label ${String(unreachable)}`);
      }
    }
    if (campaign.score !== null) {
      if (flagValue(campaign.score, "false_quarantine")) {
        falseQuarantine += 1;
      }
      if (campaign.score.kind === "instruction" && flagValue(campaign.score, "contaminated")) {
        lenientContamination += 1;
      }
      if (campaign.score.kind === "record_update" && flagValue(campaign.score, "record_inconsistent")) {
        recordInconsistent += 1;
      }
      if (countActionFlags(campaign.score) > 0) {
        laterActionFlags += 1;
      }
    }
    for (const channel of skillChannels(campaign)) {
      if (channel.decision.kind === "loaded-despite-untrusted") {
        untrustedLoadedLater += 1;
      }
    }
  }
  return {
    campaigns: campaigns.length,
    complete,
    incomplete,
    trustedSkills,
    untrustedSkills,
    falseQuarantine,
    lenientContamination,
    recordInconsistent,
    laterActionFlags,
    untrustedLoadedLater,
  };
}
