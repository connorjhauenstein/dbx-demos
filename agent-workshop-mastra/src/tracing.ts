import { trace as otelTrace, SpanStatusCode } from '@opentelemetry/api';
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node';
import { BatchSpanProcessor, type SpanExporter, type ReadableSpan } from '@opentelemetry/sdk-trace-base';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-proto';
import { resourceFromAttributes } from '@opentelemetry/resources';
import type { ExportResult } from '@opentelemetry/core';
import { getToken } from './auth';

// MLflow span type values (set as the mlflow.spanType attribute).
export const SpanType = { AGENT: 'AGENT', LLM: 'LLM', CHAIN: 'CHAIN', TOOL: 'TOOL', CHAT_MODEL: 'CHAT_MODEL' } as const;

let tracer: ReturnType<typeof otelTrace.getTracer> | null = null;
let provider: NodeTracerProvider | null = null;

// OTLP exporter that refreshes its bearer token before expiry, so a long-running
// server (or App) keeps exporting. Databricks auth: CLI token locally, M2M in-App.
class RefreshingOtlpExporter implements SpanExporter {
  private exp: OTLPTraceExporter | null = null;
  private expiresAt = 0;
  constructor(private url: string, private ucTable: string) {}
  private async ensure(): Promise<OTLPTraceExporter> {
    if (this.exp && Date.now() < this.expiresAt - 60_000) return this.exp;
    const token = await getToken();
    this.exp = new OTLPTraceExporter({
      url: this.url,
      headers: {
        'content-type': 'application/x-protobuf',
        'X-Databricks-UC-Table-Name': this.ucTable,
        Authorization: `Bearer ${token}`,
      },
    });
    this.expiresAt = Date.now() + 45 * 60 * 1000;
    return this.exp;
  }
  export(spans: ReadableSpan[], resultCallback: (result: ExportResult) => void) {
    this.ensure()
      .then((e) => e.export(spans, resultCallback))
      .catch((error) => resultCallback({ code: 1, error } as ExportResult));
  }
  async shutdown() { await this.exp?.shutdown(); }
  async forceFlush() { await (this.exp as any)?.forceFlush?.(); }
}

export async function initTracing(): Promise<boolean> {
  if (tracer) return true;
  const host = (process.env.DATABRICKS_HOST ?? '').replace(/\/$/, '');
  const ucTable = process.env.MLFLOW_UC_TRACE_TABLE; // e.g. catalog.schema.agent_traces_otel_spans
  if (!host || !ucTable) {
    console.warn('[tracing] DATABRICKS_HOST or MLFLOW_UC_TRACE_TABLE not set — tracing disabled');
    return false;
  }
  try {
    await getToken(); // fail fast if auth is broken
    provider = new NodeTracerProvider({
      resource: resourceFromAttributes({ 'service.name': 'agent-workshop-mastra' }),
      spanProcessors: [new BatchSpanProcessor(new RefreshingOtlpExporter(`${host}/api/2.0/otel/v1/traces`, ucTable))],
    });
    provider.register();
    tracer = otelTrace.getTracer('agent-workshop-mastra');
    console.log(`[tracing] OTLP → ${ucTable}`);
    return true;
  } catch (e) {
    console.error('[tracing] init failed (continuing without tracing):', e);
    return false;
  }
}

export type SpanCtl = {
  setOutputs: (o: unknown) => void;
  setAttributes: (a: Record<string, unknown>) => void;
};

// Set an OTel attribute, preserving numbers/booleans (e.g. token counts) and
// JSON-encoding objects.
function setAttr(span: any, key: string, value: unknown) {
  if (value === null || value === undefined) return;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') {
    span.setAttribute(key, value);
  } else {
    span.setAttribute(key, JSON.stringify(value));
  }
}

// Run fn inside an OTel span carrying MLflow input/output attributes. No-op if disabled.
// Nested traced() calls become child spans via OTel active-context propagation.
export async function traced<T>(
  opts: { name: string; spanType?: string; inputs?: unknown; attributes?: Record<string, unknown> },
  fn: (ctl: SpanCtl) => Promise<T>,
): Promise<T> {
  if (!tracer) return fn({ setOutputs: () => {}, setAttributes: () => {} });
  return tracer.startActiveSpan(opts.name, async (span) => {
    if (opts.spanType) span.setAttribute('mlflow.spanType', JSON.stringify(opts.spanType));
    if (opts.inputs !== undefined) span.setAttribute('mlflow.spanInputs', JSON.stringify(opts.inputs));
    for (const [k, v] of Object.entries(opts.attributes ?? {})) setAttr(span, k, v);
    const ctl: SpanCtl = {
      setOutputs: (o) => span.setAttribute('mlflow.spanOutputs', JSON.stringify(o)),
      setAttributes: (a) => { for (const [k, v] of Object.entries(a)) setAttr(span, k, v); },
    };
    try {
      const result = await fn(ctl);
      span.setStatus({ code: SpanStatusCode.OK });
      return result;
    } catch (e) {
      span.setStatus({ code: SpanStatusCode.ERROR, message: String(e) });
      ctl.setOutputs({ error: String(e) });
      throw e;
    } finally {
      span.end();
    }
  });
}

export async function flush(): Promise<void> {
  if (provider) {
    try { await provider.forceFlush(); } catch { /* ignore */ }
  }
}
