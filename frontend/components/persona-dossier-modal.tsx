"use client";

import type { DossierResponse, Source } from "../lib/api";

export type PersonaDossierModalProps = {
  isOpen: boolean;
  personName: string | null;
  dossier: DossierResponse | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onSelectCitation?: (source: Source) => void;
};

export { PersonaDossierModal } from "./persona-dossier-modal.mjs";
