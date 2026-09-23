#!/usr/bin/env bash
# Check Azure Container Apps serverless-GPU eligibility in a SECOND tenant
# without disturbing the Azure CLI session already in use.
#
# Isolation: AZURE_CONFIG_DIR redirects the entire CLI profile and token cache
# to a scratch directory, so the default ~/.azure profile is never written to.
# Any other process using the default context keeps working unchanged.
#
# Usage:
#   ./check_gpu_quota.sh login <tenant-id-or-domain>
#   ./check_gpu_quota.sh check [subscription-id]
#   ./check_gpu_quota.sh logout

set -uo pipefail

export AZURE_CONFIG_DIR="${AZURE_CONFIG_DIR_OVERRIDE:-/tmp/az-tenant2}"

# Regions that currently offer Container Apps serverless GPU.
GPU_REGIONS=(westus3 swedencentral australiaeast northcentralus westeurope southeastasia)

banner() { printf '\n\033[1m%s\033[0m\n' "$*"; }

cmd_login() {
  local tenant="${1:?usage: $0 login <tenant-id-or-domain>}"
  mkdir -p "$AZURE_CONFIG_DIR"
  banner "Logging in to tenant $tenant (isolated profile: $AZURE_CONFIG_DIR)"
  echo "Your existing ~/.azure session is NOT modified."
  az login --tenant "$tenant" --use-device-code --only-show-errors -o table
}

cmd_check() {
  local sub="${1:-}"
  if [[ -n "$sub" ]]; then
    az account set --subscription "$sub" --only-show-errors
  fi

  banner "1. Subscriptions visible in this tenant"
  az account list --query "[].{name:name, id:id, state:state, quotaSource:tenantId}" -o table 2>/dev/null

  local subid subname
  subid=$(az account show --query id -o tsv 2>/dev/null)
  subname=$(az account show --query name -o tsv 2>/dev/null)
  if [[ -z "$subid" ]]; then
    echo "Not logged in. Run: $0 login <tenant>"
    return 1
  fi
  banner "Checking subscription: $subname ($subid)"

  banner "2. Subscription offer type (decides whether GPU quota is grantable)"
  az rest --method get \
    --url "https://management.azure.com/subscriptions/$subid?api-version=2022-12-01" \
    --query "{quotaId:subscriptionPolicies.quotaId, spendingLimit:subscriptionPolicies.spendingLimit}" \
    -o table 2>/dev/null

  banner "3. Microsoft.App provider registration"
  az provider show -n Microsoft.App --query "{namespace:namespace, state:registrationState}" -o table 2>/dev/null

  banner "4. Serverless GPU workload profiles offered, by region"
  printf '%-18s %s\n' "REGION" "GPU PROFILES AVAILABLE"
  for region in "${GPU_REGIONS[@]}"; do
    local profiles
    profiles=$(az rest --method get \
      --url "https://management.azure.com/subscriptions/$subid/providers/Microsoft.App/locations/$region/availableManagedEnvironmentsWorkloadProfileTypes?api-version=2024-03-01" \
      --query "value[?contains(name,'GPU')].name" -o tsv 2>/dev/null | tr '\n' ' ')
    if [[ -n "${profiles// /}" ]]; then
      printf '%-18s \033[32m%s\033[0m\n' "$region" "$profiles"
    else
      printf '%-18s %s\n' "$region" "-"
    fi
  done

  banner "5. Container Apps GPU quota (the number that actually blocks you)"
  printf '%-18s %-34s %s\n' "REGION" "QUOTA NAME" "USED/LIMIT"
  local found=0
  for region in "${GPU_REGIONS[@]}"; do
    while IFS=$'\t' read -r qname used limit; do
      [[ -z "$qname" ]] && continue
      found=1
      local colour='\033[32m'
      [[ "${limit:-0}" == "0" ]] && colour='\033[31m'
      printf '%-18s %-34s '"$colour"'%s/%s\033[0m\n' "$region" "$qname" "$used" "$limit"
    done < <(az rest --method get \
      --url "https://management.azure.com/subscriptions/$subid/providers/Microsoft.App/locations/$region/usages?api-version=2024-03-01" \
      --query "value[?contains(name.value,'GPU')].[name.value, currentValue, limit]" -o tsv 2>/dev/null)
  done
  [[ "$found" == "0" ]] && echo "(no GPU quota entries returned in any region)"

  banner "6. Underlying VM GPU family quota"
  printf '%-18s %-40s %s\n' "REGION" "FAMILY" "USED/LIMIT"
  for region in "${GPU_REGIONS[@]}"; do
    while IFS=$'\t' read -r fname used limit; do
      [[ -z "$fname" ]] && continue
      local colour='\033[32m'
      [[ "${limit:-0}" == "0" ]] && colour='\033[31m'
      printf '%-18s %-40s '"$colour"'%s/%s\033[0m\n' "$region" "$fname" "$used" "$limit"
    done < <(az vm list-usage --location "$region" \
      --query "[?contains(name.value,'NC') || contains(name.value,'ND') || contains(name.value,'NV')].[name.value, currentValue, limit]" \
      -o tsv --only-show-errors 2>/dev/null)
  done

  banner "Verdict"
  echo "Deployable only if BOTH hold:"
  echo "  - a region in step 4 lists a Consumption-GPU profile, AND"
  echo "  - that region shows a non-zero limit in step 5 or 6."
  echo "Green numbers above are usable; red zeros mean a quota request is required."
}

cmd_probe() {
  local region="${1:?usage: $0 probe <region> [profile]}"
  local profile="${2:-Consumption-GPU-NC8as-T4}"
  local rg="rg-gpuprobe-$region"
  local env="env-gpuprobe-$region"

  banner "Definitive probe: add $profile in $region"
  echo "The usages API does not report serverless-GPU quota, so the only"
  echo "conclusive test is asking the control plane for the profile itself."
  echo "Creating an environment costs nothing; the GPU profile bills only"
  echo "while a GPU container is actually running. Nothing is deployed here."
  echo

  az group create -n "$rg" -l "$region" --only-show-errors -o none 2>/dev/null \
    || { echo "Could not create resource group in $region."; return 1; }

  az containerapp env create -n "$env" -g "$rg" -l "$region" \
    --enable-workload-profiles true --only-show-errors -o none 2>&1 | tail -3

  local out rc
  out=$(az containerapp env workload-profile add -n "$env" -g "$rg" \
    --workload-profile-name gpuprobe --workload-profile-type "$profile" \
    --only-show-errors 2>&1)
  rc=$?

  if [[ $rc -eq 0 ]]; then
    printf '\033[32mGPU PROFILE ACCEPTED\033[0m — %s is usable in %s.\n' "$profile" "$region"
    echo "This tenant can host Laya on GPU."
  else
    printf '\033[31mREJECTED\033[0m — %s not usable in %s:\n' "$profile" "$region"
    echo "$out" | tail -5
    echo
    echo "A message mentioning quota/capacity means a quota request is needed."
  fi

  echo
  echo "Clean up when done:  az group delete -n $rg --yes --no-wait"
}

cmd_logout() {
  banner "Clearing isolated profile only"
  az logout --only-show-errors 2>/dev/null
  rm -rf "$AZURE_CONFIG_DIR"
  echo "Removed $AZURE_CONFIG_DIR. Default ~/.azure untouched."
}

case "${1:-}" in
  login)  shift; cmd_login "$@" ;;
  check)  shift; cmd_check "$@" ;;
  probe)  shift; cmd_probe "$@" ;;
  logout) cmd_logout ;;
  *) echo "usage: $0 {login <tenant>|check [sub-id]|probe <region> [profile]|logout}"; exit 1 ;;
esac
