# Challenges & Solutions

A running log of real problems encountered while building this project, how
they were diagnosed, and what fixed them. Updated as the build progresses.

---

## 1. Wrong CPU architecture for the Terraform binary

**Problem:** Downloaded the ARM64 build of Terraform for a Windows virtual
desktop and it wouldn't run.

**Diagnosis:** Checked the actual architecture with
`echo %PROCESSOR_ARCHITECTURE%`, which returned `AMD64` — the VM runs on
x86-64 hardware, so the ARM64 binary was incompatible.

**Fix:** Downloaded the AMD64 build instead.

**Lesson:** "AMD64" means 64-bit x86 (Intel or AMD), not AMD-brand hardware.
Verify the target architecture before downloading platform-specific binaries.

## 2. `terraform` not recognized despite being installed

**Problem:** `terraform -version` failed with "not recognized as an internal
or external command" even after adding an entry to PATH.

**Diagnosis:** Isolated the problem by calling the binary with its full path
(`C:\terraform\terraform.exe -version`), which worked — proving the exe was
fine and the issue was PATH resolution. Root causes found: (a) the PATH entry
initially pointed to a folder name that didn't match the extracted folder, and
(b) the terminal being used had been opened *before* the PATH change, and
Windows terminals only read environment variables at launch.

**Fix:** Ensured the exe lived at the exact path listed in PATH, then opened a
fresh terminal.

**Lesson:** Full-path invocation is the fastest way to separate "binary
broken" from "PATH broken". Environment variable changes never affect
already-open terminals.

## 3. Guide commands written for bash failing on Windows CMD

**Problem:** Multiple commands failed in odd ways: `az ad sp create-for-rbac`
rejected its arguments, `export` didn't exist, and `$(date +%Y-%m-01)` was
passed through literally.

**Diagnosis:** The commands used Linux shell conventions — `\` line
continuations (which CMD treats as literal text, silently mangling the `--`
flag prefixes), `export` for environment variables, and `$(...)` command
substitution.

**Fix:** Translated to CMD equivalents: single-line commands with explicit
`--flag` syntax, `set VAR=value` instead of `export`, and hardcoded dates
instead of shell substitution.

**Lesson:** Shell dialect matters. When following documentation, identify
which shell it targets before copy-pasting.

## 4. Azure CLI budget command rejected by the API

**Problem:** `az consumption budget create` failed with
`(400) Invalid budget configuration, please use filter interface with
2019-05-01-preview version`.

**Diagnosis:** The `az consumption` command group is in preview and pinned to
an API version the budgets backend no longer accepts — a known gap between
the CLI and the service.

**Fix:** Created the budget (with 50/80/100% email alerts) through the Azure
Portal's Cost Management blade instead.

**Lesson:** Not everything needs to be scripted. For one-time governance
setup, the Portal is a legitimate tool — the IaC principle applies to
resources that must be reproducible, not to every click.

## 5. Service principal couldn't create role assignments (403)

**Problem:** `terraform apply` failed on both `azurerm_role_assignment`
resources with `AuthorizationFailed ... Microsoft.Authorization/roleAssignments/write`.

**Diagnosis:** The deployment service principal had the Contributor role,
which can create and manage resources but deliberately cannot grant RBAC
roles — otherwise any Contributor could escalate its own privileges. The
Terraform config assigns roles to managed identities (ADF → storage), so the
SP needed that specific extra capability.

**Fix:** Granted the SP the "Role Based Access Control Administrator" role at
subscription scope — a narrower alternative to Owner that permits managing
role assignments without other elevated rights.

**Lesson:** Contributor ≠ full control. Privilege boundaries in Azure RBAC
are intentional; grant the minimum additional role that unblocks the specific
action.

## 6. Azure SQL provisioning blocked in the chosen region

**Problem:** Creating the SQL server in `eastus2` failed with
`ProvisioningDisabled: Provisioning is restricted in this region`.

**Diagnosis:** Free-tier / new subscriptions are subject to per-region
capacity restrictions for Azure SQL, and eastus2 was closed to new SQL
provisioning for this subscription.

**Fix:** Parameterized the SQL server's region separately
(`var.sql_location`) and deployed it to a different region, keeping the rest
of the platform in place. Mixed-region resource groups are fully supported.

**Lesson:** Region capacity is a real-world constraint, not a config error.
Designing per-service location variables makes the infrastructure resilient
to it.

## 7. Ghost SQL server from a failed create (409 Conflict)

**Problem:** After switching regions, the retry failed with
`InvalidResourceLocation: The resource 'sql-ecomlake-dev' already exists in
location 'eastus2'` — even though the original create had reported failure.

**Diagnosis:** The failed eastus2 provisioning left a partially-registered
server that Azure still counted against the (globally unique) server name,
while Terraform's state knew nothing about it because the create had returned
an error.

**Fix:** Listed servers in the resource group with
`az sql server list`, deleted the orphan with `az sql server delete`, and
re-ran `terraform apply`, letting Terraform converge by creating only the
missing resources.

**Lesson:** Failed cloud operations can leave orphaned state that exists in
the provider but not in Terraform's state file. When Terraform and reality
disagree, inspect reality directly with the CLI before changing code.

## 8. Databricks workspace access denied on first login

**Problem:** Opening the workspace URL returned "Unable to view page — you do not
have permission to access this page in workspace ...", despite owning the
subscription.

**Diagnosis:** The workspace was created by Terraform using the deployment
service principal. Navigating directly to the raw `adb-*.azuredatabricks.net`
URL skips the Azure AD SSO handoff that provisions a user into the workspace on
first entry.

**Fix:** Launched the workspace from the Azure Portal instead (Databricks
resource → "Launch Workspace"), which performed the handoff and provisioned the
account as a workspace admin.

**Lesson:** Resource ownership in Azure and user membership in a Databricks
workspace are separate concepts. Enter a new workspace through the Portal at
least once.

## 9. Cluster creation blocked by regional vCPU quota

**Problem:** Cluster creation failed with `AZURE_QUOTA_EXCEEDED_EXCEPTION` —
"Current Limit: 10, Current Usage: 8, New Limit Required: 12".

**Diagnosis:** The default subscription quota in eastus2 was 10 total regional
vCPUs, of which 8 were already consumed (all in the Standard BS family). The
initial cluster config compounded the problem: autoscaling 2–8 workers plus
Photon requested 36 cores for a workload that needs a fraction of that.

**Fix:** Right-sized the cluster first — single node, no autoscaling, Photon
disabled, 4-core general-purpose node, 20-minute auto-termination — then
submitted self-service quota increases for both "Total Regional vCPUs" and the
relevant family limit.

**Lesson:** Azure enforces quota at both regional and VM-family level; raising
one without the other still blocks. Equally important: the default cluster form
is sized for production workloads, not portfolio data — always right-size before
blaming quota.

## 10. Unity Catalog blocks cluster-level storage credentials

**Problem:** Reading `abfss://` paths failed repeatedly with
`Invalid configuration value detected for fs.azure.account.key`, and setting
OAuth credentials in the notebook failed with
`CONFIG_NOT_AVAILABLE ... SQLSTATE 42K0I`.

**Diagnosis:** The workspace is Unity Catalog-governed and the cluster ran in
"Auto" access mode, which resolves to a UC-managed mode. In that mode, `fs.azure.*`
Spark configurations are not merely ignored — they are inaccessible, so neither
notebook-level `spark.conf.set()` nor cluster-level Spark config had any effect.
The service-principal-plus-`spark.conf` pattern found in most tutorials only
works on non-UC or dedicated-access clusters.

**Fix:** Adopted the Unity Catalog-native path instead of fighting it:
1. Created a Databricks Access Connector (system-assigned managed identity).
2. Granted that identity **Storage Blob Data Contributor** on the storage account.
3. Registered a UC **storage credential** referencing the connector.
4. Created a UC **external location** per container (bronze, silver, gold,
   quarantine, checkpoints).

Validation reported Read/List/Write/Delete/Path/HNS all successful, with only
optional "file events" checks failing (they require additional queue and
EventGrid roles and only affect ingestion performance, so the locations were
force-created).

**Lesson:** Unity Catalog centralises storage governance by design — credentials
belong to the metastore, not to clusters or notebooks. When an error says a
configuration is "not available" rather than "incorrect", the platform is
telling you the mechanism is disabled, not misconfigured. Recognising that
distinction early would have saved several hours.

## 11. Secrets repeatedly exposed during troubleshooting

**Problem:** Over the course of debugging, several live credentials (SQL admin
password, Event Hubs shared access key, service principal client secret) were
pasted into terminals, chat logs, and screenshots.

**Diagnosis:** Debugging encourages copy-pasting whole commands and outputs, and
secrets travel with them. Screenshots leak just as effectively as text.

**Fix:** Rotated each exposed credential (`az ad sp credential reset`,
`az eventhubs ... keys renew`, SQL admin password update) and moved secrets out
of code into environment variables and Databricks secret scopes.

**Lesson:** Adopt a redaction habit before pasting anything: scan for keys,
passwords, and connection strings and replace them with placeholders. Error
messages almost never require the secret itself to diagnose.

## 12. Duplicate EntityPath in the Kafka JAAS configuration

**Problem:** The reference code for the streaming consumer appended
`;EntityPath=clickstream` to the Event Hubs connection string when building the
Kafka JAAS config.

**Diagnosis:** The Terraform authorization rule is scoped to the event hub
rather than the namespace, so the connection string it produces *already* ends
with `EntityPath=clickstream`. Appending it a second time produces a malformed
JAAS string, and the resulting failure surfaces as a generic authentication or
connection timeout — nothing in the error points at the duplicated parameter.

**Fix:** Verified the suffix before use with
`conn.endswith("EntityPath=clickstream")` and passed the connection string
unmodified when the check returned true.

**Lesson:** Connection strings differ depending on the scope of the
authorization rule that generated them (namespace-level vs entity-level).
Inspect the string's shape rather than assuming, and prefer a cheap assertion
over debugging a misleading downstream error.

## 13. Event Hubs Basic tier has no Kafka endpoint

**Problem:** The Structured Streaming consumer could not connect to Event Hubs
over the Kafka protocol.

**Diagnosis:** The namespace had been provisioned with `sku = "Basic"`.
The Kafka-compatible endpoint (port 9093) is a Standard-tier feature; on Basic
it simply does not exist. The failure appears as a connection/authentication
error rather than an explicit "feature not available" message, which makes the
root cause non-obvious.

**Fix:** Changed the tier to `Standard` in Terraform and re-applied, confirming
from the plan that the namespace was updated in place rather than replaced
(replacement would regenerate access keys and invalidate the connection string
stored in Key Vault).

**Lesson:** Service tiers gate protocols, not just throughput and quotas. When
choosing a cheaper tier, check the feature matrix for the specific protocol the
architecture depends on. The additional cost (roughly $22/month versus $11) is
the price of Kafka-protocol compatibility, which in turn keeps the consumer code
portable to a real Kafka cluster — a worthwhile trade documented in
`design-decisions.md`.

## 14. Terraform state lost with a deleted dev VM

**Problem.** A development VM was deleted, taking its local `terraform.tfstate`
with it. The infrastructure still existed in Azure, but Terraform no longer knew
about any of it — `terraform plan` showed all 20 resources as "to add."

**Diagnosis.** Local state is a single point of failure. Applying the plan would
have tried to recreate resources that already existed, producing 409 conflicts.

**Fix.** Reconciled 16 live resources into a fresh state with `terraform import`,
parents before children (resource group → storage account → filesystems →
namespaces → children). The stragglers (Key Vault secret, role assignments, SQL
firewall rule) surfaced as 409s on the first apply and were imported individually.
Then configured a remote `azurerm` backend and migrated state into it, so the
failure mode cannot recur.

**Lesson.** Remote state is not optional polish — it survives machine loss and is
a prerequisite for CI/CD. The backend block must also be committed: a later fresh
clone reverted to empty local state because the backend configuration existed only
on the lost machine, never in the repo.

## 15. Metadata-driven pipeline silently skipped tables not in the control table

**Problem.** After the first successful ADF run, two source tables (`sellers`,
`order_reviews`) had no data in bronze, yet the pipeline reported success.

**Diagnosis.** Both tables were missing from `etl.ingest_control`. The ForEach only
iterates the control table, so tables absent from it are never copied — and the
pipeline still succeeds because it did everything it was told.

**Fix.** Added the missing control rows. Re-ran; both tables landed.

**Lesson.** "Pipeline succeeded" is not "data arrived." A metadata-driven design
trades a code change for a data change, but the cost is that an omission in the
metadata fails silently. This motivated the sink-verification and row-count checks.

## 16. Watermark advanced on a misdirected copy, skipping ~99k rows

**Problem.** After fixing an incorrect sink path, a re-run of the incremental copy
returned almost no rows, and the silver referential-integrity assertion fired with
112,650 orphaned order_items — because `orders` in bronze was nearly empty.

**Diagnosis.** The first (misdirected) run had written orders to the wrong path but
still advanced the watermark to the latest `order_purchase_timestamp`, because the
watermark update depended on Copy *success*, not on verified landing. The corrected
run then queried for rows after that advanced watermark and correctly found none.

**Fix.** Reset the watermark, and restructured the pipeline so a Get Metadata
activity verifies files exist at the sink before the watermark update commits. The
update throws on failure, holding the watermark so the next run reprocesses.

**Lesson.** State that records progress must only advance after the effect it
describes is verified, not after the operation that intends it returns success.

## 17. ADF forbids nested If Condition activities

**Problem.** The sink-verification design placed an If Condition (advance watermark
vs. fail) inside the existing full-load/incremental If Condition. ADF rejected it:
"If Condition activity is not allowed under an If Condition Activity."

**Diagnosis.** ADF does not permit control-flow activities (If, ForEach, Switch,
Until) to be nested directly inside one another.

**Fix.** Moved the verification gate out of a second If and into the Script
activity's T-SQL: `IF exists AND childItems > 0 THEN update watermark ELSE THROW`.
Same guarantee, no nested control flow.

**Lesson.** ADF's control-flow nesting limits push conditional logic beyond one
level into activity dependencies or into the activity's own payload.

## 18. Quarantine ran correctly but its predicate omitted user_id

**Problem.** The data-quality gate reported 636 null-`user_id` rows in silver, even
though the quarantine mechanism was working.

**Diagnosis.** The silver quality predicate checked `event_id`, `event_ts`,
`event_type`, and `price` — but not `user_id`. So the ~3% injected null-user rows
passed validation and landed in silver. The quarantine table was empty not because
the split failed, but because nothing matched its (incomplete) condition.

**Fix.** Added `user_id IS NOT NULL` to the predicate and reason codes to the
quarantine output, then deleted silver/quarantine and their checkpoints and
replayed from bronze.

**Lesson.** A test of the mechanism ("does quarantine write work?") would have
passed. What caught this was a downstream check asserting a *property of silver*.
Test outcomes, not mechanisms.

## 19. Streaming checkpoint bound to a deleted table's identity

**Problem.** After deleting and recreating a silver table, a downstream streaming
query failed: "The streaming query was reading from an unexpected Delta table
(id = ...). It used to read from another Delta table (id = ...)."

**Diagnosis.** A streaming checkpoint records the *identity* of its source table,
not just its path. Recreating the table at the same path gives it a new table ID,
which no longer matches the checkpoint.

**Fix.** Deleted the downstream checkpoint (and its output table) so the stream
reinitialised against the new table.

**Lesson.** When a table is deleted and rebuilt, every checkpoint of every stream
reading from it must be cleared too. Same principle as the watermark: state
describing a relationship becomes invalid when one side is replaced.

## 20. Job clusters denied access to Unity Catalog external locations

**Problem.** The orchestrated pipeline failed where interactive runs succeeded:
"User does not have READ FILES on External Location 'ext-checkpoints'."

**Diagnosis.** Interactive and job compute run under different principals. The
external-location grants made while setting up Unity Catalog applied to the
interactive user, not to the identity the ADF-triggered job cluster runs as.

**Fix.** Granted READ/WRITE FILES on all five external locations to the job's
principal (to `account users` in this dev project).

**Lesson.** A permission that passes interactively can fail in the orchestrated
run because the principal differs — exactly the kind of gap only an end-to-end run
surfaces.

## 21. Pipeline "succeeded" while running an outdated notebook

**Problem.** A full pipeline run completed green, but the gold layer was missing
`dim_date` entirely and the unknown dimension member, causing a downstream
data-quality failure.

**Diagnosis.** The ADF notebook activity pointed at an older copy of notebook 03
that predated those additions. It ran without error — it simply did less than the
corrected version — so ADF reported success.

**Fix.** Pointed the activity at the corrected notebook (committed in the Git
folder) and re-ran.

**Lesson.** Green status signals intent, not verified effect — the third instance
of this principle in the project. Notebooks referenced by orchestration must be the
same artifacts under version control, or "it worked when I ran it" and "the
pipeline runs it" diverge.

## 22. CI passed locally but failed on the runner (import + formatting)

**Problem.** The first real CI run failed on two jobs: `ModuleNotFoundError: No
module named 'src'` in the tests, and `terraform fmt -check` returning non-zero.

**Diagnosis.** The tests passed locally because they were run from inside the
project folder; the CI runner's working directory differed, so `from src...` did
not resolve. Separately, the `.tf` files had never been run through `terraform
fmt`.

**Fix.** Added a `pytest.ini` with `pythonpath = .` so the repo root is on the
path, and ran `terraform fmt -recursive`. Both jobs then passed.

**Lesson.** CI is worth having precisely because it runs in a clean, different
environment from the developer's — it caught an implicit-path assumption and
unformatted IaC that local runs hid.
