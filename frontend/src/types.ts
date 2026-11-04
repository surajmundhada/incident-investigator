export type Incident = {
  application?: string;
  configuration_revision?: string;
  snapshot_id?: string | null;
  id: string;
  title: string;
  service: string;
  environment: string;
  release: string;
  description: string;
  starts_at: number;
  ends_at: number;
};
export type Item = Pick<
  Incident,
  "id" | "title" | "service" | "environment" | "release"
> & {
  application?: string;
  investigation_id: string;
  status: string;
  created_at: number;
};
export type Reference = { evidence_id: string; record_index: number };
export type RunbookReference = { evidence_id: string; passage_id: string };
export type Claim = { text: string; references: Reference[] };
export type Hypothesis = {
  explanation: string;
  service: string;
  supporting: Reference[];
  contradicting: Reference[];
};
export type Passage = {
  id: string;
  title?: string;
  heading: string;
  body: string;
  source: string;
  line_start: number;
  line_end: number;
  revision_id?: string;
};
export type RecordEntry = {
  timestamp: string;
  service: string;
  level: string;
  message: string;
  request_id?: string;
  status_code?: number;
  dependency?: string;
};
export type Evidence = {
  id: string;
  source: string;
  availability: string;
  collected_at: string | number;
  service?: string;
  revision?: string;
  error?: string;
  truncated?: boolean;
  data_origin?: string;
  records?: RecordEntry[];
  hits?: Passage[];
};
export type Report = {
  summary: string;
  mode: string;
  provider_origin?: string;
  model?: string;
  conclusion?: string;
  observations?: Claim[];
  hypotheses?: Hypothesis[];
  runbook_references?: RunbookReference[];
  missing_evidence?: string[];
  suggested_checks?: string[];
  limitations?: string[];
  termination_reason?: string;
  knowledge_revision?: string;
  retrieval_profile?: string;
  usage?: {
    model_calls: number;
    tool_calls_started: number;
    model_tokens: number;
  };
};
export type Investigation = {
  id: string;
  status: string;
  attempts: number;
  incident: Incident;
  report: Report | null;
  evidence: Evidence[];
  created_at: number;
  updated_at: number;
};
export type ProgressEvent = {
  id: number;
  kind: string;
  message: string;
  created_at: number;
};

export type ApplicationConfiguration = {
  application: string;
  environment: string;
  release: string;
  revision: string;
  services: Record<string, { dependencies: string[] }>;
};
export type SnapshotSummary = {
  id: string;
  application: string;
  configuration_revision: string;
  source_name: string;
  environment: string;
  release: string;
  starts_at: number;
  ends_at: number;
  covered_services: string[];
  record_count: number;
  synthetic_example: boolean;
  coverage_basis: string;
};
