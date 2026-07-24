# Worker autoscaling (KEDA)

The base worker Deployments run a fixed `replicas: 1`. A telemetry burst or a
pile-up of scheduled exports/compliance reports just queues behind that single
pod — throughput doesn't follow load. These
[KEDA](https://keda.sh/) `ScaledObject`s scale each worker on its **consumer-group
lag** (the count of unprocessed messages), which is the signal that actually
reflects queue pressure for an I/O-bound Kafka consumer — CPU does not.

| Worker                     | Group                          | Topic                        | min→max | Notes |
|----------------------------|--------------------------------|------------------------------|---------|-------|
| ingestion-worker           | `opsgrid-ingestion-workers`    | all telemetry topics (pattern) | 2→12  | warm floor: real-time stream, no scale-to-zero |
| export-worker              | `omniusgrid-export-delivery`   | `opsgrid.exports`            | 0→8     | scale-to-zero when idle |
| compliance-reports-worker  | `omniusgrid-compliance-reports`| `opsgrid.compliance-reports` | 0→6    | scale-to-zero when idle |

The OTA rollout worker is intentionally excluded — it's a stateful DB/orchestrator
loop, not a lag-scalable Kafka consumer.

## Prerequisites

Install the KEDA operator (provides the `keda.sh/v1alpha1` CRDs; `kustomize
build` here only emits the ScaledObjects, it does not install KEDA):

```bash
kubectl apply --server-side -f \
  https://github.com/kedacore/keda/releases/download/v2.15.1/keda-2.15.1.yaml
```

## Apply

```bash
kustomize build infrastructure/k8s/autoscaling | kubectl apply -f -
```

KEDA creates one HPA per ScaledObject and takes over the replica count — the
Deployments' `replicas` field becomes the initial value only.

## Tuning

- **`maxReplicaCount` must be ≤ the topic's partition count.** Consumers beyond
  the partition count sit idle (one partition is only ever read by one consumer
  in a group), so scaling past it just burns pods. Set partitions on Redpanda to
  match the parallelism you want, then align these caps.
- **`lagThreshold`** is the per-replica target lag: KEDA aims for
  `desiredReplicas = ceil(totalLag / lagThreshold)`. Lower it for snappier
  scale-up, raise it to tolerate more backlog before adding pods.
- **Scale-to-zero** (export/compliance) trades a cold-start on the first message
  for zero idle cost. The ingestion worker keeps a warm floor of 2 so a live
  telemetry stream is never waiting on a pod to start.
