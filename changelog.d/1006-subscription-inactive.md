Fixed
An expired or unprovisioned subscription refused by the provider -- Ark
Coding's HTTP 400 `InvalidSubscription`, OpenAI's `account_deactivated`,
Anthropic's `billing_error` -- now fails the first call as `SubscriptionInactive`
instead of being retried as a transient `RuntimeError`. The run stops within
seconds instead of after three attempts per call, the error line names the
subscription as the cause, `diagnose` repeats that next step instead of
recommending `doctor`, and `resume` refuses it without `--force` (#1006).
