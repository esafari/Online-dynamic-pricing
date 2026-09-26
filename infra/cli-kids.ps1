# ============================================================
# Pricing lab → Azure (step-by-step deploy)
# Run from the Pricing folder (the directory that contains Dockerfile):
#   pwsh -File infra/cli-kids.ps1
# Requires: Azure CLI, Docker Desktop, an Azure subscription.
#
# A "resource group" is a labeled box. Everything we create goes in the box
# so we can delete the whole box later and stop paying.

$ErrorActionPreference = "Stop"

function Say($text) {
    Write-Host ""
    Write-Host ">>> $text" -ForegroundColor Cyan
}

function Wait-Kid($text) {
    Write-Host $text -ForegroundColor Yellow
    Read-Host "Press Enter to do it"
}

Say "Step 0 — Are we in the right folder?"
if (-not (Test-Path ".\Dockerfile")) {
    throw "Stop. cd to the Pricing folder (the one with Dockerfile) and run this again."
}
Write-Host "Good. Dockerfile is here."

Say "Step 1 — Log in to Azure (a browser window will open)"
Wait-Kid "You will sign in with the Microsoft account that owns the Azure subscription."
az login
az account show --query "{name:name, id:id}" -o table

Say "Step 2 — Pick names (like naming a Minecraft world)"
$Location = "canadacentral"
$EnvName  = "dev"
$Prefix   = "pds"
$Suffix   = Get-Random -Minimum 1000 -Maximum 9999
$RG       = "rg-$Prefix-$Location-$EnvName"
$ACR      = ($Prefix + "acr" + $EnvName + $Suffix).ToLower()
$ACA_ENV  = "cae-$Prefix-$EnvName"
$APP      = "ca-$Prefix-api"
$LA       = "log-$Prefix-$EnvName"
$KV       = "kv-$Prefix-$EnvName-$Suffix"
$APPCS    = "appcs-$Prefix-$EnvName-$Suffix"

Write-Host "Region (where the computers live): $Location   ← Canada"
Write-Host "Box name (resource group):         $RG"
Write-Host "Photo album for the app (ACR):     $ACR"
Write-Host "Write these on paper. You will need them."
Wait-Kid "Ready to create the empty box in Canada?"

Say "Step 3 — Create the resource group (the empty box)"
az group create --name $RG --location $Location
Write-Host "Box created."

Say "Step 4 — Turn on Azure features we will use"
Wait-Kid "This only registers toolboxes. It does not cost money."
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.KeyVault
az provider register --namespace Microsoft.AppConfiguration

Say "Step 5 — Build a lunchbox of the app (Docker image)"
Wait-Kid "Docker wraps our Python app so Azure can run it the same way as your PC."
docker build -t pds-api:local .
Write-Host "Lunchbox built on your computer."

Say "Step 6 — Create ACR (a cloud photo album for lunchboxes) and upload"
Wait-Kid "Azure Container Registry stores the image. Names must be globally unique — that is why we added random numbers."
az acr create --resource-group $RG --name $ACR --sku Basic --admin-enabled true
az acr login --name $ACR
docker tag pds-api:local "$ACR.azurecr.io/pds-api:v0.1.0"
docker push "$ACR.azurecr.io/pds-api:v0.1.0"
Write-Host "Lunchbox is now in the cloud album."

Say "Step 7 — Create a diary for logs (Log Analytics)"
az monitor log-analytics workspace create --resource-group $RG --workspace-name $LA --location $Location
$WS_ID  = az monitor log-analytics workspace show --resource-group $RG --workspace-name $LA --query customerId -o tsv
$WS_KEY = az monitor log-analytics workspace get-shared-keys --resource-group $RG --workspace-name $LA --query primarySharedKey -o tsv

Say "Step 8 — Create the classroom (Container Apps environment + app)"
Wait-Kid "This starts the teacher (our FastAPI lab) on Azure. It will print a https:// address."
az containerapp env create --name $ACA_ENV --resource-group $RG --location $Location --logs-workspace-id $WS_ID --logs-workspace-key $WS_KEY
az containerapp create `
    --name $APP `
    --resource-group $RG `
    --environment $ACA_ENV `
    --image "$ACR.azurecr.io/pds-api:v0.1.0" `
    --registry-server "$ACR.azurecr.io" `
    --target-port 8080 `
    --ingress external `
    --cpu 0.5 --memory 1Gi `
    --min-replicas 1 --max-replicas 3 `
    --env-vars "PDS_ENV=azure-dev" "PDS_HOST=0.0.0.0" "PDS_PORT=8080"

$FQDN = az containerapp show --resource-group $RG --name $APP --query properties.configuration.ingress.fqdn -o tsv
Write-Host ""
Write-Host "OPEN THIS IN YOUR BROWSER:" -ForegroundColor Green
Write-Host "https://$FQDN/" -ForegroundColor Green
Write-Host ""
Write-Host "Save these names:"
Write-Host "  RG=$RG"
Write-Host "  ACR=$ACR"
Write-Host "  APP=$APP"
Write-Host "  FQDN=$FQDN"

Say "Step 9 — Prove it works"
az rest --method get --uri "https://$FQDN/health" --skip-authorization-header
Write-Host "If you see status ok, the school is open."

Say "Step 10 — Optional: Key Vault (safe) + App Config (principal switch)"
Wait-Kid "Press Enter to create them, or Ctrl+C to stop here (the website already works)."
az keyvault create --name $KV --resource-group $RG --location $Location
az appconfig create --name $APPCS --resource-group $RG --location $Location --sku Free
az appconfig feature set --name $APPCS --feature pds.kill_switch --description "Serve list price only"
Write-Host "Kill switch exists (off). Turn it on later in Azure Portal → App Configuration → Feature manager."

Write-Host ""
Write-Host "YOU DID THE HARD PART." -ForegroundColor Green
Write-Host "Next (when you are ready): Redis, Cosmos, Event Hubs — see the Azure tab in the lab."
Write-Host "To delete EVERYTHING and stop paying:"
Write-Host "  az group delete --name $RG --yes --no-wait"
