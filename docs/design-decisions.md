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
Databricks SQL for serving) at the same data without copying it.

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

## 5. Why a query-in-place serving layer instead of a dedicated SQL pool?

The gold layer is already computed and stored as Delta; the serving layer only
needs to expose it over SQL for Power BI, not re-store it. A dedicated SQL pool
(Synapse) starts around $1.20/hour whether or not anyone queries it, would
exhaust the free credit in days, and would require loading — duplicating — the
data into the pool. The serving layer here queries the Delta tables in place,
which keeps a single copy of the data and bills only for actual query compute.

The specific engine chosen for this is a **Databricks SQL Warehouse** rather than
Synapse Serverless — see decision #11 for that comparison. Both are query-in-place
options; the point of *this* decision is the query-in-place pattern over a
dedicated pool.

**Trade-off accepted:** no materialized indexes or dedicated-pool result caching,
so this approach would need re-evaluation at very large scale or under
strict-latency BI requirements.

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

---

## 7. Why the clickstream simulator injects defective data

A pipeline that only ever sees clean input demonstrates nothing — the
engineering *is* the handling of imperfection. The simulator therefore injects
four defects at known rates, each mapped to a real production failure mode and a
specific handling pattern:

| Defect (rate) | Real-world cause | Pattern applied in silver |
|---|---|---|
| Null `user_id` (~3%) | Anonymous users, tracking blockers | Validation gate → quarantine with reason code |
| Duplicate events (~2%) | At-least-once delivery, client retries | Deduplication bounded by watermark |
| Late arrivals (~3%) | Offline clients, clock skew | Event-time processing + watermark |
| Schema drift (~2%, `campaign_id`) | Upstream teams adding fields | Explicit schema declaration |

Because the rates are known, the counts are verifiable: a representative run
produced 647 quarantined and 389 deduplicated rows out of 19,890, matching the
injected 3% and 2%. Every row is accounted for, which is what makes the pipeline
trustworthy rather than merely functional.

**Trade-off accepted:** the simulator is more complex than a clean generator,
and the defect logic has to be kept in sync with the silver-layer expectations.

## 8. Why a metadata-driven ADF pipeline instead of one pipeline per table

Batch ingestion is driven by a single parameterised pipeline that reads a control
table (`etl.ingest_control`) and copies each enabled table, using a watermark
where one is configured. Adding a table is a one-row INSERT, not a code change.

**Trade-off accepted:** the indirection means a table absent from the control
table is silently never ingested — which happened during development (two tables
were omitted and the pipeline reported success while copying nothing). The lesson
was that "pipeline succeeded" is not "data arrived," which is precisely why the
sink-verification and data-quality checks exist.

## 9. Why the watermark advances only after verified landing

The incremental copy originally advanced its watermark whenever the Copy activity
returned success. A misconfigured sink path meant a copy "succeeded" while writing
to the wrong location, so the watermark advanced past data that never landed where
downstream expected it — and the next run skipped ~99,000 rows, also reporting
success. The fix inserts a Get Metadata check that confirms files exist at the
sink path before the watermark update commits; on failure it throws, holding the
watermark so the next run reprocesses the window.

**Principle:** state that records progress must only advance after the effect it
describes is verified, not after the operation that intends it returns success.
This is the same discipline behind a Delta transaction log committing after files
are written, and a streaming checkpoint advancing after a batch is durably
committed.

## 10. Why facts use an "unknown member" instead of dropping unmatched rows

Facts that cannot resolve a dimension member are assigned an explicit unknown
member (`customer_sk = -1`) rather than being dropped or left null. This keeps
`fact_orders` reconciled exactly to `silver/order_items` (no rows silently lost),
makes the unresolved rate measurable, and lets BI joins resolve to a labelled row.
The data-quality gate then monitors the unknown-member rate against a threshold
rather than demanding it be zero.

**Trade-off accepted:** a small, deliberate loss of precision (some facts point at
"unknown") in exchange for reconciling totals and observable data quality.

## 11. Why Databricks SQL Warehouse for serving instead of Synapse Serverless

Both expose the gold Delta layer to Power BI over a SQL endpoint. Serving through
a Databricks SQL Warehouse with Unity Catalog views keeps querying and governance
inside one engine, avoids provisioning a second workspace and its cost, and
reflects the current direction of querying the lakehouse in place. Synapse
Serverless remains appropriate where an organisation is already standardised on
the Synapse/Fabric ecosystem.

**Trade-off accepted:** less breadth of Azure services touched (no Synapse), in
exchange for a simpler, cheaper, single-governance serving layer.

## 12. Why transformation logic lives in `src/` rather than only in notebooks

The core transformation functions (quality filter, dedup, quarantine tagging) are
defined in `src/transforms.py` and imported by both the notebooks and the pytest
suite. One definition, two consumers. This makes the logic unit-testable on a
local Spark session in CI without a cluster or cloud access, so a change that
breaks a validation rule fails a test before it ever reaches a notebook.

**Trade-off accepted:** a small amount of indirection (notebooks import rather
than inline the logic) in exchange for testability and a single source of truth.

## 13. Credentials are fetched on demand, never stored locally

No secret is required to exist on a developer machine. The SQL password and
connection strings live in Key Vault; Terraform reads them via `TF_VAR_*`
sourced from Key Vault at session start; Databricks reads them through a
Key Vault-backed secret scope; ADF reads them through a Key Vault linked service.
A session-setup script fetches what a session needs and holds nothing.

**Trade-off accepted:** a small amount of setup friction each session, in
exchange for a machine loss costing nothing in credentials — validated when a dev
VM was lost mid-project.
