# Personalized Pricing on Azure — deploy script (Phase 1–4)
# Run from the Pricing repo root in PowerShell:
#   pwsh -File infra/azure-up.ps1
# Requires: Azure CLI, Docker Desktop, logged-in az account.

param(
    [string]$Location = "canadacentral",
    [string]$EnvName = "dev",
    [string]$Prefix = "pds"
)

$ErrorActionPreference = "Stop"
$suffix = Get-Random -Minimum 1000 -Maximum 9999
$rg = "rg-$Prefix-$Location-$EnvName"
$acr = ($Prefix + "acr" + $EnvName + $suffix).ToLower()
$envNameAca = "cae-$Prefix-$EnvName"
$appName = "ca-$Prefix-api"
$workspace = "log-$Prefix-$EnvName"
$kv = "kv-$Prefix-$EnvName-$suffix"
$appcs = "appcs-$Prefix-$EnvName-$suffix"

Write-Host "Resource group : $rg"
Write-Host "ACR            : $acr"
Write-Host "Container app  : $appName"
Write-Host "Key Vault      : $kv"

az group create --name $rg --location $Location | Out-Null

az acr create --resource-group $rg --name $acr --sku Basic --admin-enabled true | Out-Null
az acr login --name $acr

docker build -t "$acr.azurecr.io/pds-api:v0.1.0" .
docker push "$acr.azurecr.io/pds-api:v0.1.0"

az monitor log-analytics workspace create --resource-group $rg --workspace-name $workspace --location $Location | Out-Null
$workspaceId = az monitor log-analytics workspace show --resource-group $rg --workspace-name $workspace --query customerId -o tsv
$workspaceKey = az monitor log-analytics workspace get-shared-keys --resource-group $rg --workspace-name $workspace --query primarySharedKey -o tsv

az containerapp env create `
    --name $envNameAca `
    --resource-group $rg `
    --location $Location `
    --logs-workspace-id $workspaceId `
    --logs-workspace-key $workspaceKey | Out-Null

az keyvault create --name $kv --resource-group $rg --location $Location | Out-Null
az appconfig create --name $appcs --resource-group $rg --location $Location --sku Free | Out-Null

az containerapp create `
    --name $appName `
    --resource-group $rg `
    --environment $envNameAca `
    --image "$acr.azurecr.io/pds-api:v0.1.0" `
    --registry-server "$acr.azurecr.io" `
    --target-port 8080 `
    --ingress external `
    --cpu 0.5 --memory 1Gi `
    --min-replicas 1 --max-replicas 3 `
    --env-vars "PDS_ENV=azure-$EnvName" "PDS_HOST=0.0.0.0" "PDS_PORT=8080" `
    --query properties.configuration.ingress.fqdn -o tsv

Write-Host ""
Write-Host "Done. Open https://<fqdn>/  (printed above)"
Write-Host "Save these names: rg=$rg acr=$acr kv=$kv appcs=$appcs"
