$env:ARM_SUBSCRIPTION_ID = "5ce9e687-f9f0-47dc-8805-77466025c2a9"
$env:TF_VAR_sql_password = (az keyvault secret show --vault-name kv-ecomlake-dev --name sql-admin-password --query value -o tsv)
Write-Host "Environment ready"
