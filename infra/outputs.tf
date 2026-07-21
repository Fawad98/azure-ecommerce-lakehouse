output "storage_account_name" { value = azurerm_storage_account.lake.name }
output "eventhub_namespace" { value = azurerm_eventhub_namespace.ehns.name }
output "databricks_url" { value = azurerm_databricks_workspace.dbx.workspace_url }
output "adf_name" { value = azurerm_data_factory.adf.name }
output "sql_server_fqdn" { value = azurerm_mssql_server.sql.fully_qualified_domain_name }
output "eh_send_connstr" {
  value     = azurerm_eventhub_authorization_rule.send.primary_connection_string
  sensitive = true
}