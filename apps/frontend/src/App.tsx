/**
 * Multi-MCP Enterprise Operations Copilot — GUI.
 *
 * Four panels, all driven by the same stream: the answer, the execution timeline,
 * the retrieved evidence, and the tool-discovery view. Plus a confirmation dialog
 * that gates writes.
 *
 * Answer text is rendered as text, never as HTML — `dangerouslySetInnerHTML` is
 * absent by design, because retrieved document content and model output are both
 * untrusted input.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { askCopilot, fetchServers, fetchTools } from "./api";
import type {
  Citation, PlanPreview, ServerStatus, StepEvent, ToolSpec, TraceSummary,
} from "./types";

const SAMPLE_QUESTIONS = [
  "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify likely contributing factors, retrieve the relevant operating procedure, and provide recommended actions with source evidence.",
  "Calculate operator response efficiency for SouthPlant and retrieve the applicable operating guideline.",
  "Identify the highest-priority active alarm at EastRefinery and prepare an escalation summary.",
  "Find recurring alarms for Boiler Feed Pump 101 and prepare a GitHub issue draft.",
];

type Tab = "timeline" | "evidence" | "tools";

export default function App() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [plan, setPlan] = useState<PlanPreview | null>(null);
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [summary, setSummary] = useState<TraceSummary | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [pendingWrite, setPendingWrite] = useState<StepEvent | null>(null);
  const [tab, setTab] = useState<Tab>("timeline");
  const [tools, setTools] = useState<ToolSpec[]>([]);
  const [servers, setServers] = useState<ServerStatus[]>([]);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  const [expandedStep, setExpandedStep] = useState<string | null>(null);
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const answerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    Promise.all([fetchTools(), fetchServers()])
      .then(([t, s]) => { setTools(t); setServers(s); setDiscoveryError(null); })
      .catch((e) => setDiscoveryError(String(e)));
  }, []);

  useEffect(() => {
    answerRef.current?.scrollTo({ top: answerRef.current.scrollHeight });
  }, [answer]);

  const run = useCallback(
    async (text: string, confirmedActions: string[] = []) => {
      if (!text.trim() || busy) return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setBusy(true);
      setError(null);
      setAnswer("");
      setPlan(null);
      setSteps([]);
      setCitations([]);
      setSummary(null);
      setPendingWrite(null);
      setTab("timeline");

      await askCopilot(
        text,
        { conversationId, confirmedActions },
        {
          onEvent: (event, payload) => {
            switch (event) {
              case "trace.started":
                setConversationId(payload.conversation_id);
                break;
              case "plan.ready":
                setPlan(payload as PlanPreview);
                break;
              case "step.started":
              case "step.succeeded":
              case "step.failed":
                // Replace in place rather than re-sorting: arrival order *is* the
                // execution order, and step ids do not sort into it ("r1" < "s1").
                setSteps((prev) => {
                  const step = payload as StepEvent;
                  const at = prev.findIndex((s) => s.id === step.id);
                  if (at === -1) return [...prev, step];
                  const next = [...prev];
                  next[at] = step;
                  return next;
                });
                break;
              case "confirmation.required":
                setPendingWrite(payload as StepEvent);
                setSteps((prev) => {
                  const step = payload as StepEvent;
                  const at = prev.findIndex((s) => s.id === step.id);
                  if (at === -1) return [...prev, step];
                  const next = [...prev];
                  next[at] = step;
                  return next;
                });
                break;
              case "answer.delta":
                setAnswer((prev) => prev + payload.text);
                break;
              case "answer.completed":
                setCitations(payload.citations ?? []);
                setSummary(payload as TraceSummary);
                if ((payload.citations ?? []).length) setTab("evidence");
                break;
              case "error":
                setError(`${payload.error_code}: ${payload.message}`);
                break;
            }
          },
          onError: setError,
          onDone: () => setBusy(false),
        },
        controller.signal
      );
    },
    [busy, conversationId]
  );

  const citationIndex = useMemo(() => {
    const map = new Map<string, Citation>();
    citations.forEach((c) => map.set(c.citation, c));
    return map;
  }, [citations]);

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Multi-MCP Enterprise Operations Copilot</h1>
          <p className="subtitle">
            Live alarm data through MCP, grounded in operating procedures
          </p>
        </div>
        <div className="server-pills">
          {servers.length === 0 && !discoveryError && (
            <span className="pill pill-muted">connecting…</span>
          )}
          {servers.map((s) => (
            <span key={s.name} className={`pill ${s.connected ? "pill-ok" : "pill-bad"}`}
                  title={s.error ?? ""}>
              {s.name} · {s.connected ? `${s.tool_count} tools` : "unavailable"}
            </span>
          ))}
        </div>
      </header>

      <main className="layout">
        <section className="panel chat">
          <div className="panel-head"><h2>Chat</h2></div>

          <div className="answer" ref={answerRef}>
            {!answer && !busy && (
              <div className="empty">
                <p>Ask an operations question. Try one of these:</p>
                <ul className="samples">
                  {SAMPLE_QUESTIONS.map((q) => (
                    <li key={q}>
                      <button className="link" onClick={() => { setQuestion(q); run(q); }}
                              disabled={busy}>
                        {q.length > 110 ? `${q.slice(0, 110)}…` : q}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {busy && !answer && (
              <div className="loading">
                <span className="spinner" aria-hidden />
                {plan ? `Executing ${plan.steps.length} steps…` : "Planning…"}
              </div>
            )}

            {error && <div className="error" role="alert">{error}</div>}

            {answer && <AnswerText text={answer} citations={citationIndex}
                                   onCite={() => setTab("evidence")} />}

            {summary?.low_confidence && (
              <div className="warn">
                Retrieval returned nothing sufficiently relevant. No operating procedure
                supports the recommendations above.
              </div>
            )}

            {summary && (
              <div className="meta">
                {summary.total_duration_ms.toFixed(0)}ms tools ·{" "}
                {summary.llm_latency_ms.toFixed(0)}ms model · provider{" "}
                {summary.planner_provider} · trace {summary.trace_id}
              </div>
            )}
          </div>

          <form className="composer"
                onSubmit={(e) => { e.preventDefault(); run(question); }}>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. Investigate recurring alarms on Boiler Feed Pump 101…"
              rows={3}
              disabled={busy}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  run(question);
                }
              }}
            />
            <div className="composer-actions">
              <span className="hint">Ctrl/Cmd + Enter to send</span>
              <button type="submit" disabled={busy || !question.trim()}>
                {busy ? "Working…" : "Ask"}
              </button>
            </div>
          </form>
        </section>

        <section className="panel side">
          <div className="tabs" role="tablist">
            {(["timeline", "evidence", "tools"] as Tab[]).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t}
                      className={tab === t ? "tab active" : "tab"}
                      onClick={() => setTab(t)}>
                {t === "timeline" && `Execution${steps.length ? ` (${steps.length})` : ""}`}
                {t === "evidence" && `Evidence${citations.length ? ` (${citations.length})` : ""}`}
                {t === "tools" && `Tools${tools.length ? ` (${tools.length})` : ""}`}
              </button>
            ))}
          </div>

          {tab === "timeline" && (
            <Timeline steps={steps} plan={plan} busy={busy}
                      expanded={expandedStep} onExpand={setExpandedStep} />
          )}
          {tab === "evidence" && <Evidence citations={citations} busy={busy} />}
          {tab === "tools" && (
            <Discovery tools={tools} error={discoveryError}
                       expanded={expandedTool} onExpand={setExpandedTool} />
          )}
        </section>
      </main>

      {pendingWrite && (
        <ConfirmDialog
          step={pendingWrite}
          onCancel={() => setPendingWrite(null)}
          onApprove={() => {
            const tool = pendingWrite.tool;
            setPendingWrite(null);
            if (tool) run(question || SAMPLE_QUESTIONS[3], [tool]);
          }}
        />
      )}
    </div>
  );
}

/**
 * Renders the answer as plain text with citation markers turned into chips.
 *
 * Deliberately not a markdown-to-HTML renderer: the text contains model output and
 * retrieved document content, and turning either into HTML is how injected markup
 * gets executed.
 */
function AnswerText({ text, citations, onCite }: {
  text: string;
  citations: Map<string, Citation>;
  onCite: () => void;
}) {
  const parts = text.split(/(\[(?:source|tool):[^\]]+\])/g);
  return (
    <div className="answer-text">
      {parts.map((part, i) => {
        const source = /^\[source:\s*([^\]]+)\]$/.exec(part);
        if (source) {
          const key = source[1].trim();
          const found = citations.get(key);
          return (
            <button key={i} className={found ? "chip chip-source" : "chip chip-unknown"}
                    onClick={onCite}
                    title={found ? `${found.title} — ${found.section}` : "not retrieved"}>
              {key.split("#")[0]}
            </button>
          );
        }
        const tool = /^\[tool:\s*([^\]]+)\]$/.exec(part);
        if (tool) {
          return <span key={i} className="chip chip-tool">{tool[1].trim()}</span>;
        }
        return <span key={i}>{part}</span>;
      })}
    </div>
  );
}

function Timeline({ steps, plan, busy, expanded, onExpand }: {
  steps: StepEvent[]; plan: PlanPreview | null; busy: boolean;
  expanded: string | null; onExpand: (id: string | null) => void;
}) {
  if (!steps.length && !plan) {
    return <div className="empty small">
      {busy ? "Planning…" : "Ask a question to see the execution trace."}
    </div>;
  }
  return (
    <div className="scroll">
      {plan && (
        <div className="plan">
          <strong>Intent:</strong> {plan.intent}
          {plan.gaps.length > 0 && (
            <ul className="gaps">{plan.gaps.map((g) => <li key={g}>{g}</li>)}</ul>
          )}
        </div>
      )}
      {steps.map((s) => (
        <div key={s.id} className={`step step-${s.status}`}>
          <button className="step-head" onClick={() => onExpand(expanded === s.id ? null : s.id)}>
            <span className={`dot dot-${s.status}`} aria-hidden />
            <span className="step-id">{s.id}</span>
            <span className="step-server">{s.server ?? (s.kind === "retrieval" ? "rag" : "—")}</span>
            <span className="step-label">{s.label}</span>
            <span className="step-time">
              {s.status === "running" ? "…" : `${s.duration_ms.toFixed(0)}ms`}
            </span>
          </button>
          {s.reason && <div className="step-reason">{s.reason}</div>}
          {s.error_code && (
            <div className="step-error">{s.error_code}: {s.error_message}</div>
          )}
          {expanded === s.id && (
            <div className="step-detail">
              <h4>Arguments</h4>
              <pre>{JSON.stringify(s.arguments, null, 2)}</pre>
              <h4>Output</h4>
              <pre>{s.output ? JSON.stringify(s.output, null, 2) : "(none)"}</pre>
              {s.trace_id && <div className="trace">trace_id: {s.trace_id}</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Evidence({ citations, busy }: { citations: Citation[]; busy: boolean }) {
  if (!citations.length) {
    return <div className="empty small">
      {busy ? "Retrieving…" : "No document evidence yet."}
    </div>;
  }
  return (
    <div className="scroll">
      {citations.map((c) => (
        <div key={c.citation} className="citation">
          <div className="citation-head">
            <strong>{c.title}</strong>
            <span className="score">{(c.score * 100).toFixed(0)}%</span>
          </div>
          <div className="citation-section">{c.section}</div>
          {c.suspicious && (
            <div className="warn small">
              This document contains text resembling an embedded instruction. It was
              treated as data only.
            </div>
          )}
          <p className="excerpt">{c.excerpt}</p>
          <code className="marker">[source: {c.citation}]</code>
        </div>
      ))}
    </div>
  );
}

function Discovery({ tools, error, expanded, onExpand }: {
  tools: ToolSpec[]; error: string | null;
  expanded: string | null; onExpand: (name: string | null) => void;
}) {
  if (error) return <div className="error">Could not load the tool catalogue: {error}</div>;
  if (!tools.length) return <div className="empty small">Loading tools…</div>;

  const byServer = tools.reduce<Record<string, ToolSpec[]>>((acc, t) => {
    (acc[t.server] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div className="scroll">
      {Object.entries(byServer).map(([server, list]) => (
        <div key={server} className="server-group">
          <h3>{server} <span className="count">{list.length}</span></h3>
          {list.map((t) => (
            <div key={t.qualified_name} className="tool">
              <button className="tool-head"
                      onClick={() => onExpand(expanded === t.qualified_name ? null : t.qualified_name)}>
                <code>{t.name}</code>
              </button>
              <p className="tool-desc">{t.description.split("\n")[0]}</p>
              {expanded === t.qualified_name && (
                <div className="tool-detail">
                  <h4>Input schema</h4>
                  <pre>{JSON.stringify(t.input_schema, null, 2)}</pre>
                  <h4>Output schema</h4>
                  <pre>{t.output_schema ? JSON.stringify(t.output_schema, null, 2) : "(none)"}</pre>
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/** Gates a write. The MCP server refuses without approval regardless of this dialog. */
function ConfirmDialog({ step, onApprove, onCancel }: {
  step: StepEvent; onApprove: () => void; onCancel: () => void;
}) {
  return (
    <div className="overlay" role="dialog" aria-modal="true">
      <div className="dialog">
        <h3>Approve this action?</h3>
        <p>
          <code>{step.tool}</code> writes to an external system. It will not run
          without your approval.
        </p>
        <pre>{JSON.stringify(step.arguments, null, 2)}</pre>
        <div className="dialog-actions">
          <button className="secondary" onClick={onCancel}>Cancel</button>
          <button onClick={onApprove}>Approve and run</button>
        </div>
      </div>
    </div>
  );
}
