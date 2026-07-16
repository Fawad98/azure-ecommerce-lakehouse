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
