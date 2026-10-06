
import { apiEnvoyer } from "@/core/api/client";
import type { Briefing } from "./briefing.types";

export async function chargerBriefing(filtres: Record<string, unknown>): Promise<Briefing> {
  try {
    return await (await apiEnvoyer("/api/fleet/briefing", filtres)).json();
  } catch {
    return { error: "analyse indisponible" };
  }
}
