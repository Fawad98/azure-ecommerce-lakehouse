resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.prefix}"
  location = var.location
  tags     = local.tags
}

# ---------- Data Lake (ADLS Gen2) ----------
resource "azurerm_storage_account" "lake" {
  name                     = replace("st${local.prefix}", "-", "")
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"          # cheapest; fine for a portfolio
  is_hns_enabled           = true           # THIS makes it ADLS Gen2
  tags                     = local.tags
}

resource "azurerm_storage_data_lake_gen2_filesystem" "zones" {
  for_each           = toset(["bronze", "silver", "gold", "quarantine", "checkpoints"])
  name               = each.key
  storage_account_id = azurerm_storage_account.lake.id
}

# ---------- Event Hubs ----------
resource "azurerm_eventhub_namespace" "ehns" {
  name                = "ehns-${local.prefix}"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Standard"             # Basic is enough & cheap
  capacity            = 1
  tags                = local.tags
}

resource "azurerm_eventhub" "clickstream" {
  name              = "clickstream"
  namespace_id      = azurerm_eventhub_namespace.ehns.id
  partition_count   = 2
  message_retention = 1
}

resource "azurerm_eventhub_authorization_rule" "send" {
  name         = "simulator-send"
  namespace_name      = azurerm_eventhub_namespace.ehns.name
  eventhub_name       = azurerm_eventhub.clickstream.name
  resource_group_name = azurerm_resource_group.rg.name
  send = true
}

resource "azurerm_eventhub_authorization_rule" "listen" {
  name         = "databricks-listen"
  namespace_name      = azurerm_eventhub_namespace.ehns.name
  eventhub_name       = azurerm_eventhub.clickstream.name
  resource_group_name = azurerm_resource_group.rg.name
  listen = true
}

# ---------- Key Vault ----------
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "kv" {
  name                = "kv-${local.prefix}"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"
  rbac_authorization_enabled = true
  tags                = local.tags
}

resource "azurerm_role_assignment" "kv_admin" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "eh_listen" {
  name         = "eventhub-listen-connstr"
  value        = azurerm_eventhub_authorization_rule.listen.primary_connection_string
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.kv_admin]
}

# ---------- Azure SQL (simulated operational source) ----------
resource "azurerm_mssql_server" "sql" {
  name                         = "sql-${local.prefix}"
  resource_group_name          = azurerm_resource_group.rg.name
  location                     = var.sql_location
  version                      = "12.0"
  administrator_login          = "lakeadmin"
  administrator_login_password = var.sql_password   # pass via TF_VAR_sql_password
}

resource "azurerm_mssql_database" "olist" {
  name      = "olist"
  server_id = azurerm_mssql_server.sql.id
  sku_name  = "Basic"            # ~$5/month
}

resource "azurerm_mssql_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# ---------- Data Factory ----------
resource "azurerm_data_factory" "adf" {
  name                = "adf-${local.prefix}"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  identity { type = "SystemAssigned" }
  tags = local.tags
}

# Give ADF's managed identity access to the lake
resource "azurerm_role_assignment" "adf_lake" {
  scope                = azurerm_storage_account.lake.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_data_factory.adf.identity[0].principal_id
}

# ---------- Databricks ----------
resource "azurerm_databricks_workspace" "dbx" {
  name                = "dbx-${local.prefix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  sku                 = "premium"   # needed for RBAC / Unity Catalog
  tags                = local.tags
}