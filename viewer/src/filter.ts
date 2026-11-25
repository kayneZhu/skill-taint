import type { Campaign, CampaignQuery } from "./types.js";

export function filterCampaigns(
  campaigns: readonly Campaign[],
  query: CampaignQuery,
): Campaign[] {
  const needle = query.text.trim().toLowerCase();
  return campaigns.filter((campaign) => matches(campaign, query, needle));
}

export function uniqueShorts(campaigns: readonly Campaign[]): string[] {
  return [...new Set(campaigns.map((campaign) => campaign.short))].sort((left, right) =>
    compareStrings(left, right),
  );
}

function matches(campaign: Campaign, query: CampaignQuery, needle: string): boolean {
  if (query.short !== "all" && campaign.short !== query.short) {
    return false;
  }
  if (query.family !== "all" && campaign.family !== query.family) {
    return false;
  }
  if (query.condition !== "all" && campaign.condition !== query.condition) {
    return false;
  }
  if (query.status !== "all" && campaign.status !== query.status) {
    return false;
  }
  if (query.untrustedOnly && !campaign.skills.some((skill) => skill.label === "untrusted")) {
    return false;
  }
  if (query.lenientOnly && !hasLenientFlag(campaign)) {
    return false;
  }
  if (needle.length === 0) {
    return true;
  }
  if (campaign.campaignId.toLowerCase().includes(needle)) {
    return true;
  }
  if (campaign.model.toLowerCase().includes(needle)) {
    return true;
  }
  if (campaign.skills.some((skill) => skill.skillId.includes(needle) || skill.body.toLowerCase().includes(needle))) {
    return true;
  }
  return false;
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

function compareStrings(left: string, right: string): number {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
}
