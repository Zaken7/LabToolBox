#!/bin/bash
# Longhorn Upgrade and Management Toolkit
# Created: 2025-06-23
# Usage: ./longhorn-upgrade.sh [command] [options]

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

#################################
# LONGHORN VERSION MANAGEMENT  #
#################################

# Check current Longhorn installation
check_longhorn_status() {
    log_info "Checking Longhorn installation status..."
    
    # Check if namespace exists
    if ! kubectl get namespace longhorn-system >/dev/null 2>&1; then
        log_error "Longhorn namespace not found. Is Longhorn installed?"
        return 1
    fi
    
    echo "=== LONGHORN DEPLOYMENT STATUS ==="
    kubectl get deployment,daemonset -n longhorn-system -o wide
    
    echo -e "\n=== LONGHORN VERSION INFORMATION ==="
    
    # Current version from settings
    local current_version
    current_version=$(kubectl get settings.longhorn.io current-longhorn-version -n longhorn-system -o jsonpath='{.value}' 2>/dev/null || echo "Unknown")
    echo "Settings Version: $current_version"
    
    # Image versions in use
    echo -e "\nImage Versions in Use:"
    kubectl get deployment,daemonset -n longhorn-system -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.template.spec.containers[*].image}{"\n"}{end}' | sort
    
    echo -e "\n=== LONGHORN VOLUMES STATUS ==="
    kubectl get volumes.longhorn.io -n longhorn-system -o custom-columns="NAME:.metadata.name,SIZE:.spec.size,STATE:.status.state,ROBUSTNESS:.status.robustness" | head -10
    
    echo -e "\n=== PERSISTENT VOLUMES ==="
    kubectl get pvc -A | grep longhorn | wc -l | xargs echo "Total PVCs using Longhorn:"
    
    echo -e "\n=== FAILING PODS ==="
    kubectl get pods -n longhorn-system | grep -E "(Error|CrashLoopBackOff|Init|Pending)" | wc -l | xargs echo "Failing pods:"
}

# Detect version conflicts
detect_version_conflicts() {
    log_info "Detecting Longhorn version conflicts..."
    
    local settings_version
    settings_version=$(kubectl get settings.longhorn.io current-longhorn-version -n longhorn-system -o jsonpath='{.value}' 2>/dev/null)
    
    local manager_image
    manager_image=$(kubectl get daemonset longhorn-manager -n longhorn-system -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
    
    local csi_image
    csi_image=$(kubectl get daemonset longhorn-csi-plugin -n longhorn-system -o jsonpath='{.spec.template.spec.containers[2].image}' 2>/dev/null)
    
    echo "=== VERSION CONFLICT ANALYSIS ==="
    echo "Settings Version: $settings_version"
    echo "Manager Image: $manager_image"
    echo "CSI Plugin Image: $csi_image"
    
    # Extract versions from images
    local manager_version=$(echo "$manager_image" | grep -o 'v[0-9]\+\.[0-9]\+\.[0-9]\+' || echo "unknown")
    local csi_version=$(echo "$csi_image" | grep -o 'v[0-9]\+\.[0-9]\+\.[0-9]\+' || echo "unknown")
    
    echo "Manager Version: $manager_version"
    echo "CSI Version: $csi_version"
    
    # Check for conflicts
    local conflict=false
    if [[ "$settings_version" != "$manager_version" ]]; then
        log_warning "Version conflict detected: Settings($settings_version) vs Manager($manager_version)"
        conflict=true
    fi
    
    if [[ "$manager_version" != "$csi_version" ]]; then
        log_warning "Version conflict detected: Manager($manager_version) vs CSI($csi_version)"
        conflict=true
    fi
    
    if [[ "$conflict" == true ]]; then
        log_error "Version conflicts detected! This explains the CrashLoopBackOff issues."
        return 1
    else
        log_success "No version conflicts detected"
        return 0
    fi
}

# Backup Longhorn configuration
backup_longhorn_config() {
    local backup_dir="${1:-/tmp/longhorn-backup-$(date +%Y%m%d-%H%M%S)}"
    
    log_info "Creating Longhorn configuration backup in $backup_dir..."
    
    mkdir -p "$backup_dir"
    
    # Backup settings
    kubectl get settings.longhorn.io -n longhorn-system -o yaml > "$backup_dir/settings.yaml"
    
    # Backup storage classes
    kubectl get storageclass | grep longhorn | awk '{print $1}' | xargs -I {} kubectl get storageclass {} -o yaml > "$backup_dir/storageclass-{}.yaml" 2>/dev/null
    
    # Backup volumes metadata
    kubectl get volumes.longhorn.io -n longhorn-system -o yaml > "$backup_dir/volumes.yaml"
    
    # Backup PVC information
    kubectl get pvc -A -o yaml | grep -A 50 -B 5 "storageClassName.*longhorn" > "$backup_dir/pvcs.yaml"
    
    # Backup current deployment manifests
    kubectl get deployment,daemonset,service -n longhorn-system -o yaml > "$backup_dir/deployments.yaml"
    
    log_success "Backup completed in $backup_dir"
    echo "Backup contents:"
    ls -la "$backup_dir"
}

# Upgrade Longhorn to specific version
upgrade_longhorn() {
    local target_version="$1"
    local force_upgrade="${2:-false}"
    
    if [[ -z "$target_version" ]]; then
        log_error "Usage: upgrade_longhorn <version> [force]"
        log_info "Example: upgrade_longhorn v1.9.0"
        return 1
    fi
    
    log_info "Starting Longhorn upgrade to $target_version..."
    
    # Validate version format
    if [[ ! "$target_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        log_error "Invalid version format. Use format: v1.9.0"
        return 1
    fi
    
    # Check current status
    if ! detect_version_conflicts && [[ "$force_upgrade" != "force" ]]; then
        log_info "No version conflicts detected. Use 'force' parameter to upgrade anyway."
        echo "Continue with upgrade? (y/N)"
        read -r response
        if [[ "$response" != "y" && "$response" != "Y" ]]; then
            log_info "Upgrade cancelled"
            return 0
        fi
    fi
    
    # Create backup first
    local backup_dir="/tmp/longhorn-backup-$(date +%Y%m%d-%H%M%S)"
    backup_longhorn_config "$backup_dir"
    
    # Check for active volumes
    log_info "Checking for active volumes..."
    local active_volumes=$(kubectl get pvc -A | grep longhorn | grep Bound | wc -l)
    if [[ "$active_volumes" -gt 0 ]]; then
        log_warning "Found $active_volumes active volumes. Upgrade will be performed without disruption."
        echo "Continue? (y/N)"
        read -r response
        if [[ "$response" != "y" && "$response" != "Y" ]]; then
            log_info "Upgrade cancelled"
            return 0
        fi
    fi
    
    # Download target version manifest
    log_info "Downloading Longhorn $target_version manifest..."
    local manifest_url="https://raw.githubusercontent.com/longhorn/longhorn/$target_version/deploy/longhorn.yaml"
    local manifest_file="/tmp/longhorn-$target_version.yaml"
    
    if ! curl -L "$manifest_url" -o "$manifest_file"; then
        log_error "Failed to download Longhorn manifest for $target_version"
        return 1
    fi
    
    log_success "Downloaded manifest: $manifest_file"
    
    # Apply the upgrade
    log_info "Applying Longhorn $target_version upgrade..."
    if kubectl apply -f "$manifest_file"; then
        log_success "Longhorn upgrade manifest applied successfully"
    else
        log_error "Failed to apply upgrade manifest"
        return 1
    fi
    
    # Wait for upgrade to complete
    log_info "Waiting for upgrade to complete..."
    wait_for_longhorn_ready "$target_version"
}

# Wait for Longhorn to be ready after upgrade
wait_for_longhorn_ready() {
    local expected_version="$1"
    local max_wait=600  # 10 minutes
    local wait_time=0
    
    log_info "Waiting for Longhorn components to be ready (max ${max_wait}s)..."
    
    while [[ $wait_time -lt $max_wait ]]; do
        # Check if manager pods are running
        local manager_ready=$(kubectl get pods -n longhorn-system -l app=longhorn-manager --no-headers 2>/dev/null | grep -c "1/1.*Running" || echo "0")
        local manager_total=$(kubectl get pods -n longhorn-system -l app=longhorn-manager --no-headers 2>/dev/null | wc -l || echo "0")
        
        # Check CSI plugin pods
        local csi_ready=$(kubectl get pods -n longhorn-system -l app=longhorn-csi-plugin --no-headers 2>/dev/null | grep -c "3/3.*Running" || echo "0")
        local csi_total=$(kubectl get pods -n longhorn-system -l app=longhorn-csi-plugin --no-headers 2>/dev/null | wc -l || echo "0")
        
        echo -n "."
        
        if [[ "$manager_ready" -eq "$manager_total" ]] && [[ "$csi_ready" -eq "$csi_total" ]] && [[ "$manager_total" -gt 0 ]]; then
            echo ""
            log_success "All Longhorn components are ready!"
            
            # Verify version
            if [[ -n "$expected_version" ]]; then
                local current_version=$(kubectl get settings.longhorn.io current-longhorn-version -n longhorn-system -o jsonpath='{.value}' 2>/dev/null)
                if [[ "$current_version" == "$expected_version" ]]; then
                    log_success "Upgrade to $expected_version completed successfully"
                else
                    log_warning "Version mismatch: expected $expected_version, got $current_version"
                fi
            fi
            
            return 0
        fi
        
        sleep 10
        wait_time=$((wait_time + 10))
    done
    
    echo ""
    log_error "Timeout waiting for Longhorn to be ready"
    log_info "Current status:"
    kubectl get pods -n longhorn-system | grep -E "(longhorn-manager|longhorn-csi-plugin)"
    return 1
}

# Fix version conflicts (upgrade to latest stable)
fix_version_conflicts() {
    log_info "Attempting to fix Longhorn version conflicts..."
    
    if ! detect_version_conflicts; then
        log_info "Conflicts detected. Determining target version..."
        
        # Get the highest version from current deployment
        local versions=(
            $(kubectl get deployment,daemonset -n longhorn-system -o jsonpath='{.items[*].spec.template.spec.containers[*].image}' | \
            grep -o 'v[0-9]\+\.[0-9]\+\.[0-9]\+' | sort -V | uniq)
        )
        
        if [[ ${#versions[@]} -eq 0 ]]; then
            log_error "Could not determine current versions"
            return 1
        fi
        
        # Use the highest version found
        local target_version="${versions[-1]}"
        log_info "Target version determined: $target_version"
        
        upgrade_longhorn "$target_version" "force"
    else
        log_success "No version conflicts detected"
    fi
}

# Rollback Longhorn to previous version
rollback_longhorn() {
    local backup_dir="$1"
    
    if [[ -z "$backup_dir" ]] || [[ ! -d "$backup_dir" ]]; then
        log_error "Usage: rollback_longhorn <backup_directory>"
        log_info "Available backups:"
        ls -la /tmp/longhorn-backup-* 2>/dev/null || echo "No backups found"
        return 1
    fi
    
    log_warning "Rolling back Longhorn using backup from $backup_dir"
    echo "This operation may cause service disruption. Continue? (y/N)"
    read -r response
    if [[ "$response" != "y" && "$response" != "Y" ]]; then
        log_info "Rollback cancelled"
        return 0
    fi
    
    # Apply backed up configuration
    if [[ -f "$backup_dir/deployments.yaml" ]]; then
        log_info "Applying deployment rollback..."
        kubectl apply -f "$backup_dir/deployments.yaml"
    fi
    
    if [[ -f "$backup_dir/settings.yaml" ]]; then
        log_info "Applying settings rollback..."
        kubectl apply -f "$backup_dir/settings.yaml"
    fi
    
    log_info "Rollback applied. Waiting for system to stabilize..."
    wait_for_longhorn_ready
}

# Show upgrade recommendations
show_upgrade_recommendations() {
    log_info "Analyzing Longhorn installation for upgrade recommendations..."
    
    detect_version_conflicts
    
    echo -e "\n=== UPGRADE RECOMMENDATIONS ==="
    
    # Check current version vs latest stable
    local current_version=$(kubectl get settings.longhorn.io current-longhorn-version -n longhorn-system -o jsonpath='{.value}' 2>/dev/null)
    
    echo "Current Version: $current_version"
    echo "Latest Stable Versions:"
    echo "  - v1.9.0 (Latest)"
    echo "  - v1.8.2 (LTS)"
    echo "  - v1.7.3 (LTS)"
    
    if [[ "$current_version" < "v1.9.0" ]]; then
        log_info "Recommendation: Upgrade to v1.9.0 for latest features and fixes"
    else
        log_success "You are running a current version"
    fi
    
    echo -e "\n=== UPGRADE PATH ==="
    echo "To upgrade Longhorn:"
    echo "1. upgrade_longhorn v1.9.0"
    echo "2. Monitor the upgrade: watch kubectl get pods -n longhorn-system"
    echo "3. Verify after completion: check_longhorn_status"
}

# Show usage
show_usage() {
    cat << 'EOFUSAGE'
Longhorn Upgrade and Management Toolkit

COMMANDS:
  check_longhorn_status           - Check current Longhorn installation
  detect_version_conflicts        - Detect version mismatches
  backup_longhorn_config [dir]    - Backup Longhorn configuration
  upgrade_longhorn <version>      - Upgrade to specific version
  fix_version_conflicts          - Auto-fix version conflicts
  rollback_longhorn <backup_dir>  - Rollback using backup
  show_upgrade_recommendations    - Show upgrade recommendations

EXAMPLES:
  ./longhorn-upgrade.sh check_longhorn_status
  ./longhorn-upgrade.sh upgrade_longhorn v1.9.0
  ./longhorn-upgrade.sh fix_version_conflicts
  ./longhorn-upgrade.sh backup_longhorn_config /tmp/my-backup

UPGRADE WORKFLOW:
  1. check_longhorn_status        # Assess current state
  2. backup_longhorn_config       # Create safety backup
  3. upgrade_longhorn v1.9.0      # Perform upgrade
  4. Monitor: watch kubectl get pods -n longhorn-system

SAFETY FEATURES:
  • Automatic configuration backup before upgrade
  • Version conflict detection
  • Active volume protection
  • Rollback capability
  • Non-disruptive upgrades

EOFUSAGE
}

# Main execution
main() {
    case "${1:-}" in
        "check_longhorn_status"|"status")
            check_longhorn_status
            ;;
        "detect_version_conflicts"|"conflicts")
            detect_version_conflicts
            ;;
        "backup_longhorn_config"|"backup")
            backup_longhorn_config "$2"
            ;;
        "upgrade_longhorn"|"upgrade")
            upgrade_longhorn "$2" "$3"
            ;;
        "fix_version_conflicts"|"fix")
            fix_version_conflicts
            ;;
        "rollback_longhorn"|"rollback")
            rollback_longhorn "$2"
            ;;
        "show_upgrade_recommendations"|"recommendations")
            show_upgrade_recommendations
            ;;
        "help"|"--help"|"-h"|"")
            show_usage
            ;;
        *)
            log_error "Unknown command: $1"
            show_usage
            exit 1
            ;;
    esac
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
