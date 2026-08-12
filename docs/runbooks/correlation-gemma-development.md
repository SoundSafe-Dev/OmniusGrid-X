# Correlation Gemma development setup

Set `CORRELATION_MODEL_ENABLED=true` only when both artifacts are available:

- `CORRELATION_BASE_MODEL` points to a Transformers-loadable Gemma base model.
- `CORRELATION_ADAPTER_PATH` points to the directory containing the trained LoRA adapter.

The API now preloads this pair during startup. If either package, model, or adapter is unavailable, startup fails with an actionable error instead of presenting heuristic correlation output as Gemma inference. Leave `CORRELATION_MODEL_ENABLED=false` for normal local development; the UI labels those heuristic replies clearly.
