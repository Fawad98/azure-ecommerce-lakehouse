# Design Decisions — Azure E-Commerce Lakehouse

This document records the key architectural choices for this project, the
alternatives considered, and the reasoning behind each decision.

---

## 1. Why a lakehouse (Delta on ADLS Gen2) instead of a traditional warehouse?

This project ingests both semi-structured streaming JSON (clickstream) and
structured relational data (orders), and a traditional warehouse forces all
data through rigid schemas and expensive compute before it can even land. A
lakehouse stores raw data cheaply on ADLS Gen2 object storage while Delta Lake
adds the warehouse features I still need — ACID transactions, schema
enforcement, time travel, and MERGE support. It also decouples storage from
compute, so I can point multiple engines (Databricks for transformation,
Synapse Serverless for serving) at the same data without copying it.

**Trade-off accepted:** more moving parts to manage than an all-in-one
warehouse, and query performance depends on my own file layout discipline
(partitioning, OPTIMIZE/Z-ORDER) rather than a database engine handling it
for me.

## 2. Why Databricks for transformation instead of Synapse Spark or Fabric?

Databricks is the most mature Spark platform: it created Delta Lake, so
features like Structured Streaming with Delta sinks, MERGE, and Auto Loader
are first-class rather than ported. It is also the most in-demand skill of the
three in data engineering job postings, which matters for a portfolio project.
Synapse Spark pools are slower to start and lag on Spark/Delta versions;
Microsoft Fabric is promising but newer, and its capacity-based pricing model
is harder to keep inside a free-credit budget than Databricks job clusters
that spin up, run, and terminate.

**Trade-off accepted:** an extra vendor in the stack (Databricks alongside
Azure-native services) and PAT/secret management between ADF and Databricks.

## 3. Why Event Hubs instead of Kafka or IoT Hub for streaming?

Event Hubs is Azure's managed event-ingestion service: no brokers to run,
per-hour pricing in cents at 1 throughput unit, and native Azure integration
(Key Vault, RBAC, Capture to storage). Crucially, its Standard tier exposes a
Kafka-compatible endpoint, so my Spark consumer code uses the standard Kafka
connector — meaning the skill and the code transfer directly to a real Kafka
environment. Self-hosting Kafka (or paying for Confluent/HDInsight) adds
operational burden with no learning payoff at this scale, and IoT Hub targets
device-to-cloud scenarios (device identity, cloud-to-device messaging) that
this use case doesn't have — at a higher price.

**Trade-off accepted:** vendor lock-in relative to open-source Kafka, and the
Basic tier had to be upgraded to Standard for the Kafka endpoint.

## 4. Why medallion (bronze/silver/gold) layering?

Each layer has a single responsibility, which makes the pipeline debuggable
and reprocessable. Bronze stores payloads exactly as received, so if a
transformation bug is discovered later I can replay history instead of asking
the source to resend. Silver holds validated, deduplicated, conformed
entities that any downstream consumer can trust. Gold holds
business-modelled tables (star schema) optimized for consumption. The layering
also creates a natural quarantine point: records failing validation are
diverted between bronze and silver rather than silently corrupting reports.

**Trade-off accepted:** data is stored (and transformed) multiple times, so
storage cost and pipeline latency are higher than a single-hop design — a
good trade at this scale since storage is nearly free.

## 5. Why Synapse Serverless for serving instead of a dedicated SQL pool?

The gold layer is already computed and stored as Delta; the serving layer only
needs to expose it over T-SQL for Power BI. Synapse Serverless queries the
lake in place with OPENROWSET and bills ~$5 per TB scanned — with this
project's data volume in megabytes, queries cost effectively nothing. A
dedicated SQL pool starts around $1.20/hour whether or not anyone queries it,
would exhaust the free credit in days, and would require loading (duplicating)
the data into the pool. Serverless also demonstrates the modern
"query-in-place" pattern that dedicated pools are moving away from.

**Trade-off accepted:** no materialized indexes or resultset caching, so
serverless would need re-evaluation at large scale or strict-latency BI
workloads.

## 6. Service Level Agreements (SLAs)

| Data | Target | Mechanism |
|---|---|---|
| Clickstream events → bronze | ≤ 2 minutes from event publication | Structured Streaming, 1-minute trigger |
| Clickstream events → silver (validated) | ≤ 5 minutes | Streaming bronze→silver job, 1-minute trigger |
| Hourly event aggregates → gold | ≤ 15 minutes after the hour closes | Streaming aggregate, 2-hour watermark for late data |
| Batch (orders, customers) → gold | Daily by 07:00 local, covering data through previous midnight | ADF scheduled trigger + Databricks job cluster |
| Late-arriving events | Correctly attributed if ≤ 2 hours late; dropped and counted beyond that | Watermark configuration |
| Data quality | Zero failed DQ checks in gold; failures halt the pipeline and alert within 15 minutes | DQ gate notebook + Azure Monitor alert |

**Recovery objectives:** any pipeline run must be safely re-runnable
(idempotent); a full rebuild of silver and gold from bronze must be possible
within one working day.

## 7. Why the event simulator injects messy data

The simulator deliberately produces defective events, because a pipeline
that only handles clean input demonstrates nothing. Each defect type maps
to a real production failure mode and a named engineering pattern:

| Defect (rate) | Real-world cause | Handling pattern (silver layer) |
|---|---|---|
| NULL user_id (3%) | Anonymous users, tracking blockers, client bugs | Validation gate → quarantine zone (auditable, reprocessable) |
| Duplicate events (2%) | At-least-once delivery semantics, network retries | Deduplication bounded by a watermark |
| Late arrivals up to 2h (3%) | Offline mobile clients, buffering, clock skew | Event-time processing with a 2-hour watermark |
| Schema drift: campaign_id (2%) | Upstream teams shipping fields unannounced | Explicit schema evolution in the silver schema |
