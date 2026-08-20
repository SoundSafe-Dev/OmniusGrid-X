# Alertmanager secret files — local development defaults

Alertmanager **does not expand environment variables in its configuration**. The compose
config previously carried `${SLACK_WEBHOOK_URL}` and `${PAGERDUTY_SERVICE_KEY}` as
literal strings, which is not merely "unexpanded" — it is invalid:

```
$ amtool check-config infra/prometheus/alertmanager.yml
FAILED: unsupported scheme "" for URL
```

Alertmanager **refuses to start** on a config it cannot parse. So the local stack has
never had a working Alertmanager, every alert Prometheus produced went nowhere, and
`prometheus.yml` pointing at `alertmanager:9093` was pointing at a container in a restart
loop. This is the same shape as FS-516, where a removed CLI flag meant nobody running the
stack locally had ever had metrics at all.

The files here are the local-development defaults, mounted at
`/etc/alertmanager/secrets/`. They are **not secrets** — they point at localhost, so
delivery fails visibly (in the Alertmanager log, and via the `AlertNotificationsFailing`
alert) rather than invisibly. That is the intended local behaviour: you can see routing
work end to end without giving a development stack the ability to page anyone.

Real deployments do not use these. The cluster mounts the `alertmanager-secrets` Secret
over the same paths — see `infrastructure/k8s/monitoring/alertmanager-config.yml`, which
has used `*_file` correctly since it was written.

To wire a real webhook locally, overwrite the file contents; do not commit the result.

| file | receiver |
|---|---|
| `slack-webhook-url` | `default`, `slack-high`, `slack-medium` |
| `pagerduty-service-key` | `pagerduty-critical` |
| `watchdog-heartbeat-url` | `watchdog` (the dead-man's switch, FS-784) |
