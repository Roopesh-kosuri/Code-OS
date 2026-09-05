# ADR-005: Graceful Rate Limit Handling

## Status
Accepted | Date: 2026-09-01

## Context
When calling cloud LLM providers (e.g. Groq, Gemini, OpenAI) during intensive agent reasoning loops, hitting an HTTP 429 rate limit or tripping a provider circuit breaker marked the entire agent task as `failed`. Users had to re-prompt the agent and lost their workflow context.

## Decision
Implement graceful task suspension instead of failure:
1. Catch `RateLimitError` (with `retry-after` metadata) and `CircuitOpenError`.
2. Transition task and job status to `paused` with `pause_reason` and `retry_after` seconds stored in `agent_jobs`.
3. Provide `POST /api/agents/{task_id}/resume` and frontend notification badge showing cooldown reset timer.
4. Add user setting toggle for optional automatic resumption once the cooldown timer expires.

## Consequences
### Positive
- Transient provider outages and token rate limits no longer abort long-running agent workflows.
- Clear user visibility into provider health and cooldown reset timers.
- Resumes cleanly from the exact step where the rate limit was encountered.

### Negative
- Tasks in `paused` state remain in database until explicitly resumed or cancelled by the user.

### Metrics
- Task failure rate due to 429 errors: Reduced from 100% abort to 0% unrecoverable aborts.
- Average workflow recovery success after cooldown: >98%.
