# Architecture

Azure data engineering platform combining streaming and batch ingestion into a Delta Lake medallion architecture, served through serverless SQL to Power BI.

![Architecture diagram](docs/images/architecture.png)

## Data flow

### Streaming path
A **Python event simulator** generates JSON clickstream events and publishes them to **Azure Event Hubs**. **Azure Databricks** consumes the stream via **Structured Streaming** and writes the raw events into the Bronze layer of the lake.

### Batch path
**Azure SQL Database** holds the Olist operational data. **Azure Data Factory** performs a **watermark-based incremental load** from it, landing raw extracts into the Bronze layer.

### Lakehouse — ADLS Gen2 (Delta Lake)
All data lands in **Azure Data Lake Storage Gen2** as Delta tables, organized in three medallion layers:

- **Bronze (raw)** — untouched ingested data from both the streaming and batch paths
- **Silver (validated)** — cleaned, deduplicated, schema-enforced data
- **Gold (star schema)** — dimensional model ready for analytics

**Azure Databricks** handles all transformations between layers (Bronze → Silver → Gold) using **PySpark** with **MERGE / SCD2** logic for incremental upserts and slowly changing dimensions.

### Serving
**Azure Synapse Analytics (serverless SQL)** queries the Gold layer directly, exposing it to **Power BI** dashboards.

## Platform (cross-cutting)

- **Azure Key Vault** — secrets and connection-string management
- **Azure Monitor** — logging, metrics, and alerting across the pipeline
- **Terraform** — infrastructure as code for all Azure resources
- **GitHub Actions** — CI/CD for pipelines, notebooks, and infrastructure
