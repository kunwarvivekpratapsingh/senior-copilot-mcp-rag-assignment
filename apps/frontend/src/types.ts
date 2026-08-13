/** Shapes the backend streams. Mirrors copilot_backend.orchestrator.models. */

export type StepStatus =
  | "pending" | "running" | "succeeded" | "failed" | "skipped";

export interface StepEvent {
  id: string;
  kind: "tool" | "retrieval";
  label: string;
  status: StepStatus;
  server: string | null;
  tool: string | null;
  arguments: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  duration_ms: number;
  trace_id: string | null;
  reason: string;
}

export interface Citation {
  citation: string;
  doc_id: string;
  title: string;
  section: string;
  score: number;
  excerpt: string;
  source_path: string;
  suspicious: boolean;
}

export interface PlanPreview {
  intent: string;
  gaps: string[];
  steps: { id: string; kind: string; tool: string | null; reason: string;
           args: Record<string, unknown> }[];
}

export interface ToolSpec {
  server: string;
  name: string;
  qualified_name: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown> | null;
}

export interface ServerStatus {
  name: string;
  connected: boolean;
  tool_count: number;
  error: string | null;
}

export interface TraceSummary {
  request_id: string;
  trace_id: string;
  citations: Citation[];
  low_confidence: boolean;
  total_duration_ms: number;
  llm_latency_ms: number;
  planner_provider: string;
  gaps: string[];
}
