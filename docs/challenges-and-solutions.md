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
