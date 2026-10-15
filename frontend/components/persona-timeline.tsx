"use client";

import type { TimelineEvent, Source } from "@/lib/api";

export type PersonaTimelineProps = {
  personName: string | null;
  events: TimelineEvent[] | null;
  loading?: boolean;
  onSelectCitation?: (source: Source) => void;
  onSelectPerson?: (personName: string) => void;
  onGenerateDossier?: (personName: string) => void;
};

export { PersonaTimeline } from "./persona-timeline.mjs";
