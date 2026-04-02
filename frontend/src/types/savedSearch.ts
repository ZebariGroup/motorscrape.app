import type { AlertCriteria } from "@/types/alerts";

export type SavedSearchCriteria = AlertCriteria;

export type SavedSearch = {
  id: string;
  name: string;
  criteria: SavedSearchCriteria;
  created_at: string | null;
  updated_at: string | null;
};

export type SavedSearchListResponse = {
  saved_searches: SavedSearch[];
};
