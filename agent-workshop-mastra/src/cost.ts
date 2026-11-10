// Cost is OPT-IN. We do NOT emit estimated cost — Databricks bills FM endpoints in
// DBUs at contract-specific rates, so any guessed USD figure would be misleading.
// Returns null unless BOTH real per-1M-token rates are explicitly configured via env
// (PRICE_INPUT_PER_M / PRICE_OUTPUT_PER_M). When null, callers skip the mlflow.llm.cost
// attribute, so the trace simply has no cost rather than a fake one.
const IN = process.env.PRICE_INPUT_PER_M ? Number(process.env.PRICE_INPUT_PER_M) : null;
const OUT = process.env.PRICE_OUTPUT_PER_M ? Number(process.env.PRICE_OUTPUT_PER_M) : null;

export function computeCost(inputTokens = 0, outputTokens = 0) {
  if (IN == null || OUT == null) return null;
  const input_cost = (inputTokens / 1_000_000) * IN;
  const output_cost = (outputTokens / 1_000_000) * OUT;
  return { input_cost, output_cost, total_cost: input_cost + output_cost };
}
