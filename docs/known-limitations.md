# Known Limitations — CODE OS v5.0.0

## Token Accounting & Governance
- **Exact Token Accounting**: Exact provider token accounting deferred to v5.5.x; v5.0.0 uses conservative byte-based estimation when tiktoken absent (`ceil(len(text.encode('utf-8')) / 2)`).
- **Safety Guarantee**: The conservative estimator deliberately over-compacts when necessary, guaranteeing zero underestimation or TPM rate-limit overflows.
- **Fail-Closed Policy**: Governance never fails closed on tokenizer unavailability; requests always proceed cleanly using conservative estimation. The only fail-closed condition is uncomputable byte count (e.g. non-serializable payload), which does not occur under normal operation.
