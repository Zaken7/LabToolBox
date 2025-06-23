#!/bin/bash
# Kubernetes and Longhorn Troubleshooting Scripts
# Created: 2025-06-22
# Usage: Source this file or run individual functions

# set -e removed to prevent interference with warpify

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Utility functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Source enhanced SSH troubleshooting functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/ssh-fix-automation.sh" ]]; then
    source "$SCRIPT_DIR/ssh-fix-automation.sh"
if [[ -f "$SCRIPT_DIR/longhorn-upgrade.sh" ]]; then
    source "$SCRIPT_DIR/longhorn-upgrade.sh"
fi
fi

#################################
# CLUSTER INSPECTION FUNCTIONS #
#################################

# Get cluster overview
cluster_overview() {
    log_info "Getting cluster overview..."
    echo "=== NODES ==="
    kubectl get nodes -o wide
    echo -e "\n=== NAMESPACES ==="
    kubectl get namespaces
    echo -e "\n=== CLUSTER INFO ==="
    kubectl cluster-info
}

# Check node health
check_node_health() {
    log_info "Checking node health..."
    kubectl get nodes -o custom-columns="NAME:.metadata.name,STATUS:.status.conditions[?(@.type=='Ready')].status,ROLES:.metadata.labels.node-role\.kubernetes\.io/.*,AGE:.metadata.creationTimestamp,VERSION:.status.nodeInfo.kubeletVersion"
}

# Check failing pods across all namespaces
check_failing_pods() {
    log_info "Checking for failing pods..."
    kubectl get pods --all-namespaces --field-selector=status.phase!=Running,status.phase!=Succeeded
}

# Check resource usage
check_resource_usage() {
    log_info "Checking resource usage..."
    kubectl top nodes 2>/dev/null || log_warning "Metrics server not available"
    kubectl top pods --all-namespaces 2>/dev/null || log_warning "Metrics server not available"
}

#################################
# LONGHORN SPECIFIC FUNCTIONS  #
#################################

# Get Longhorn overview
longhorn_overview() {
    log_info "Getting Longhorn overview..."
    echo "=== LONGHORN NODES ==="
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,READY:.status.conditions[?(@.type=='Ready')].status,ALLOW_SCHEDULING:.spec.allowScheduling,SCHEDULABLE:.status.diskStatus.*.conditions[?(@.type=='Schedulable')].status"
    
    echo -e "\n=== LONGHORN VOLUMES ==="
    kubectl get volumes.longhorn.io -n longhorn-system -o custom-columns="NAME:.metadata.name,SIZE:.spec.size,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID"
    
    echo -e "\n=== LONGHORN SETTINGS ==="
    kubectl get settings.longhorn.io -n longhorn-system -o custom-columns="NAME:.metadata.name,VALUE:.value"
}

# Check Longhorn storage status
longhorn_storage_status() {
    log_info "Checking Longhorn storage status..."
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,SCHEDULABLE:.status.diskStatus.*.conditions[?(@.type=='Schedulable')].status,AVAILABLE:.status.diskStatus.*.storageAvailable,TOTAL:.status.diskStatus.*.storageMaximum,RESERVED:.spec.disks.*.storageReserved"
}

# Check Longhorn replicas
check_longhorn_replicas() {
    local volume_name="$1"
    if [[ -z "$volume_name" ]]; then
        log_info "Checking all Longhorn replicas..."
        kubectl get replicas.longhorn.io -n longhorn-system
    else
        log_info "Checking replicas for volume: $volume_name"
        kubectl get replicas.longhorn.io -n longhorn-system | grep "$volume_name"
    fi
}

# Configure Longhorn to use only data nodes
configure_longhorn_data_nodes_only() {
    log_info "Configuring Longhorn to use only test-k3s-data-* nodes..."
    
    # Disable scheduling on non-data nodes
    for node in test-k3s-04 test-k3s-05 test-k3s-06; do
        log_info "Disabling storage scheduling on $node..."
        kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p='{"spec":{"allowScheduling":false,"disks":{"default-disk-d7da3843ce61ab83":{"allowScheduling":false}}}}'
    done
    
    # Ensure data nodes have scheduling enabled
    for node in test-k3s-data-01 test-k3s-data-02 test-k3s-data-03; do
        log_info "Enabling storage scheduling on $node..."
        kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p='{"spec":{"allowScheduling":true,"disks":{"default-disk-d7da3843ce61ab83":{"allowScheduling":true}}}}'
    done
    
    log_success "Longhorn configured to use only data nodes"
}

# Optimize Longhorn settings for better storage utilization
optimize_longhorn_settings() {
    log_info "Optimizing Longhorn settings..."
    
    # Reduce default replica count to 2
    log_info "Setting default replica count to 2..."
    kubectl patch settings.longhorn.io default-replica-count -n longhorn-system --type='merge' -p='{"value":"2"}'
    
    # Reduce storage reservation to 20%
    log_info "Setting storage reservation to 20%..."
    kubectl patch settings.longhorn.io storage-reserved-percentage-for-default-disk -n longhorn-system --type='merge' -p='{"value":"20"}'
    
    # Update storage reservation on data nodes (for ~72GB disks)
    local reservation=$((72 * 1024 * 1024 * 1024 / 5)) # 20% of ~72GB
    for node in test-k3s-data-01 test-k3s-data-02 test-k3s-data-03; do
        log_info "Updating storage reservation on $node..."
        kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p="{\"spec\":{\"disks\":{\"default-disk-d7da3843ce61ab83\":{\"storageReserved\":14363430092}}}}"
    done
    
    log_success "Longhorn settings optimized"
}

# Fix specific volume replica count
fix_volume_replica_count() {
    local volume_name="$1"
    local replica_count="${2:-2}"
    
    if [[ -z "$volume_name" ]]; then
        log_error "Usage: fix_volume_replica_count <volume_name> [replica_count]"
        return 1
    fi
    
    log_info "Setting replica count to $replica_count for volume $volume_name..."
    kubectl patch volumes.longhorn.io "$volume_name" -n longhorn-system --type='merge' -p="{\"spec\":{\"numberOfReplicas\":$replica_count}}"
    log_success "Volume $volume_name replica count updated to $replica_count"
}

#################################
# SSH CONFIGURATION FUNCTIONS  #
#################################

# Check SSH key configuration
check_ssh_config() {
    log_info "Checking SSH configuration..."
    
    echo "=== SSH Keys ==="
    ls -la ~/.ssh/
    
    echo -e "\n=== SSH Config ==="
    if [[ -f ~/.ssh/config ]]; then
        cat ~/.ssh/config
    else
        log_warning "No SSH config file found"
    fi
    
    echo -e "\n=== SSH Agent Status ==="
    ssh-add -l 2>/dev/null || log_warning "SSH agent not running or no keys loaded"
}

# Setup SSH configuration for Kubernetes cluster
setup_ssh_config() {
    log_info "Setting up SSH configuration..."
    
    # Create SSH config
    cat > ~/.ssh/config << 'EOF'
StrictHostKeyChecking no

# Kubernetes cluster nodes
Host 192.168.145.*
    User ubuntu
    IdentityFile ~/.ssh/kube
    IdentitiesOnly yes

# Default for other hosts
Host *
    User ubuntu
    IdentityFile ~/.ssh/kube
    IdentitiesOnly yes
EOF
    
    # Set proper permissions
    chmod 600 ~/.ssh/config
    
    log_success "SSH configuration created"
}

# Test SSH connectivity to all cluster nodes
test_cluster_ssh() {
    log_info "Testing SSH connectivity to all cluster nodes..."
    
    local nodes=$(kubectl get nodes -o wide --no-headers | awk '{print $6}')
    local success=0
    local total=0
    
    for ip in $nodes; do
        echo -n "Testing $ip: "
        if timeout 10 ssh -o BatchMode=yes ubuntu@"$ip" "hostname" 2>/dev/null; then
            echo -e "${GREEN}SUCCESS${NC}"
            ((success++))
        else
            echo -e "${RED}FAILED${NC}"
        fi
        ((total++))
    done
    
    log_info "SSH test complete: $success/$total nodes accessible"
}

# Test SSH to specific IP
test_ssh_connection() {
    local ip="$1"
    local key_file="${2:-~/.ssh/kube}"
    
    if [[ -z "$ip" ]]; then
        log_error "Usage: test_ssh_connection <ip> [key_file]"
        return 1
    fi
    
    log_info "Testing SSH connection to $ip..."
    if ssh -i "$key_file" -o ConnectTimeout=5 ubuntu@"$ip" "echo 'SSH connection successful'"; then
        log_success "SSH connection to $ip successful"
    else
        log_error "SSH connection to $ip failed"
        return 1
    fi
}

#################################
# DEPLOYMENT TROUBLESHOOTING   #
#################################

# Check specific deployment status
check_deployment() {
    local deployment="$1"
    local namespace="${2:-default}"
    
    if [[ -z "$deployment" ]]; then
        log_error "Usage: check_deployment <deployment_name> [namespace]"
        return 1
    fi
    
    log_info "Checking deployment $deployment in namespace $namespace..."
    
    echo "=== DEPLOYMENT STATUS ==="
    kubectl get deployment "$deployment" -n "$namespace" -o wide
    
    echo -e "\n=== PODS ==="
    kubectl get pods -n "$namespace" -l app="$deployment"
    
    echo -e "\n=== REPLICASETS ==="
    kubectl get rs -n "$namespace" -l app="$deployment"
    
    # Get events for the deployment
    echo -e "\n=== RECENT EVENTS ==="
    kubectl get events -n "$namespace" --field-selector involvedObject.name="$deployment" --sort-by='.lastTimestamp' | tail -10
}

# Describe problematic pod
describe_pod() {
    local pod_name="$1"
    local namespace="${2:-default}"
    
    if [[ -z "$pod_name" ]]; then
        log_error "Usage: describe_pod <pod_name> [namespace]"
        return 1
    fi
    
    log_info "Describing pod $pod_name in namespace $namespace..."
    kubectl describe pod "$pod_name" -n "$namespace"
}

# Check FluxCD status
check_flux_status() {
    log_info "Checking FluxCD status..."
    
    echo "=== FLUX SYSTEM PODS ==="
    kubectl get pods -n flux-system
    
    echo -e "\n=== KUSTOMIZATIONS ==="
    kubectl get kustomizations -A
    
    echo -e "\n=== GIT REPOSITORIES ==="
    kubectl get gitrepositories -A
    
    echo -e "\n=== HELM RELEASES ==="
    kubectl get helmreleases -A
}

#################################
# PERSISTENT VOLUME FUNCTIONS  #
#################################

# Check PVC status
check_pvc_status() {
    local namespace="${1:-}"
    
    if [[ -n "$namespace" ]]; then
        log_info "Checking PVC status in namespace $namespace..."
        kubectl get pvc -n "$namespace"
    else
        log_info "Checking PVC status in all namespaces..."
        kubectl get pvc -A
    fi
}

# Check PV status
check_pv_status() {
    log_info "Checking PV status..."
    kubectl get pv -o custom-columns="NAME:.metadata.name,CAPACITY:.spec.capacity.storage,STATUS:.status.phase,CLAIM:.spec.claimRef.name,STORAGECLASS:.spec.storageClassName,AGE:.metadata.creationTimestamp"
}

# Investigate problematic PVC
investigate_pvc() {
    local pvc_name="$1"
    local namespace="${2:-default}"
    
    if [[ -z "$pvc_name" ]]; then
        log_error "Usage: investigate_pvc <pvc_name> [namespace]"
        return 1
    fi
    
    log_info "Investigating PVC $pvc_name in namespace $namespace..."
    
    echo "=== PVC DETAILS ==="
    kubectl describe pvc "$pvc_name" -n "$namespace"
    
    # Get the PV name
    local pv_name=$(kubectl get pvc "$pvc_name" -n "$namespace" -o jsonpath='{.spec.volumeName}')
    if [[ -n "$pv_name" ]]; then
        echo -e "\n=== ASSOCIATED PV DETAILS ==="
        kubectl describe pv "$pv_name"
        
        # If it's a Longhorn volume, get Longhorn details
        if kubectl get pv "$pv_name" -o jsonpath='{.spec.csi.driver}' | grep -q longhorn; then
            echo -e "\n=== LONGHORN VOLUME DETAILS ==="
            kubectl get volumes.longhorn.io -n longhorn-system "$pv_name" -o yaml
        fi
    fi
}

#################################
# MONITORING AND LOGS          #
#################################

# Get logs from problematic pods
get_pod_logs() {
    local pod_name="$1"
    local namespace="${2:-default}"
    local lines="${3:-100}"
    
    if [[ -z "$pod_name" ]]; then
        log_error "Usage: get_pod_logs <pod_name> [namespace] [lines]"
        return 1
    fi
    
    log_info "Getting logs from pod $pod_name in namespace $namespace (last $lines lines)..."
    kubectl logs "$pod_name" -n "$namespace" --tail="$lines"
    
    # Also get previous logs if available
    echo -e "\n=== PREVIOUS LOGS (if available) ==="
    kubectl logs "$pod_name" -n "$namespace" --previous --tail="$lines" 2>/dev/null || log_warning "No previous logs available"
}

# Monitor pod status in real-time
monitor_pod() {
    local pod_name="$1"
    local namespace="${2:-default}"
    
    if [[ -z "$pod_name" ]]; then
        log_error "Usage: monitor_pod <pod_name> [namespace]"
        return 1
    fi
    
    log_info "Monitoring pod $pod_name in namespace $namespace (Ctrl+C to stop)..."
    watch -n 2 "kubectl get pod $pod_name -n $namespace -o wide; echo; kubectl describe pod $pod_name -n $namespace | tail -10"
}

# Get events for troubleshooting
get_cluster_events() {
    local namespace="${1:-}"
    local lines="${2:-50}"
    
    if [[ -n "$namespace" ]]; then
        log_info "Getting recent events in namespace $namespace..."
        kubectl get events -n "$namespace" --sort-by='.lastTimestamp' | tail -"$lines"
    else
        log_info "Getting recent events across all namespaces..."
        kubectl get events --all-namespaces --sort-by='.lastTimestamp' | tail -"$lines"
    fi
}

#################################
# CLEANUP FUNCTIONS            #
#################################

# Clean up failed pods
cleanup_failed_pods() {
    local namespace="${1:-}"
    
    log_warning "This will delete all failed/evicted pods. Continue? (y/N)"
    read -r response
    if [[ "$response" != "y" && "$response" != "Y" ]]; then
        log_info "Cleanup cancelled"
        return 0
    fi
    
    if [[ -n "$namespace" ]]; then
        log_info "Cleaning up failed pods in namespace $namespace..."
        kubectl delete pods -n "$namespace" --field-selector=status.phase=Failed
        kubectl delete pods -n "$namespace" --field-selector=status.phase=Succeeded
    else
        log_info "Cleaning up failed pods in all namespaces..."
        kubectl delete pods --all-namespaces --field-selector=status.phase=Failed
        kubectl delete pods --all-namespaces --field-selector=status.phase=Succeeded
    fi
}

# Clean up completed jobs
cleanup_completed_jobs() {
    local namespace="${1:-}"
    
    log_warning "This will delete all completed jobs. Continue? (y/N)"
    read -r response
    if [[ "$response" != "y" && "$response" != "Y" ]]; then
        log_info "Cleanup cancelled"
        return 0
    fi
    
    if [[ -n "$namespace" ]]; then
        log_info "Cleaning up completed jobs in namespace $namespace..."
        kubectl delete jobs -n "$namespace" --field-selector=status.successful=1
    else
        log_info "Cleaning up completed jobs in all namespaces..."
        kubectl delete jobs --all-namespaces --field-selector=status.successful=1
    fi
}

#################################
# COMPREHENSIVE HEALTH CHECK   #
#################################

# Full cluster health check
full_health_check() {
    log_info "Starting comprehensive cluster health check..."
    
    echo "========================================="
    echo "           CLUSTER OVERVIEW"
    echo "========================================="
    cluster_overview
    
    echo -e "\n========================================="
    echo "           NODE HEALTH"
    echo "========================================="
    check_node_health
    
    echo -e "\n========================================="
    echo "           FAILING RESOURCES"
    echo "========================================="
    check_failing_pods
    
    echo -e "\n========================================="
    echo "           LONGHORN STATUS"
    echo "========================================="
    longhorn_overview
    
    echo -e "\n========================================="
    echo "           STORAGE STATUS"
    echo "========================================="
    longhorn_storage_status
    
    echo -e "\n========================================="
    echo "           PVC STATUS"
    echo "========================================="
    check_pvc_status
    
    echo -e "\n========================================="
    echo "           RECENT EVENTS"
    echo "========================================="
    get_cluster_events "" 20
    
    echo -e "\n========================================="
    echo "           SSH CONNECTIVITY"
    echo "========================================="
    test_cluster_ssh
    
    log_success "Health check completed"
}

#################################
# USAGE INFORMATION            #
#################################

show_usage() {
    cat << 'EOF'
Kubernetes and Longhorn Troubleshooting Scripts

CLUSTER INSPECTION:
  cluster_overview              - Get overall cluster status
  check_node_health            - Check node health status
  check_failing_pods           - Find pods with issues
  check_resource_usage         - Check CPU/memory usage
  full_health_check           - Comprehensive cluster check

LONGHORN FUNCTIONS:
  check_longhorn_status          - Check current Longhorn installation
  detect_version_conflicts       - Detect Longhorn version mismatches
  upgrade_longhorn <version>     - Upgrade Longhorn to specific version
  fix_version_conflicts         - Auto-fix Longhorn version conflicts
  backup_longhorn_config [dir]   - Backup Longhorn configuration
  longhorn_overview           - Get Longhorn system overview
  longhorn_storage_status     - Check storage availability
  check_longhorn_replicas [volume] - Check replica status
  configure_longhorn_data_nodes_only - Use only data nodes
  optimize_longhorn_settings  - Optimize for better utilization
  fix_volume_replica_count <volume> [count] - Fix replica count

SSH FUNCTIONS:
  fix_ssh_nodes_auto              - Enhanced SSH fix with smart automation
  check_ssh_config           - Check current SSH setup
  setup_ssh_config           - Create proper SSH config
  test_cluster_ssh           - Test SSH to all nodes
  test_ssh_connection <ip>   - Test specific connection

DEPLOYMENT TROUBLESHOOTING:
  check_deployment <name> [namespace] - Check deployment status
  describe_pod <name> [namespace]     - Get detailed pod info
  check_flux_status                   - Check FluxCD status

STORAGE FUNCTIONS:
  check_pvc_status [namespace]        - Check PVC status
  check_pv_status                     - Check PV status
  investigate_pvc <name> [namespace]  - Deep dive into PVC

MONITORING:
  get_pod_logs <name> [namespace] [lines] - Get pod logs
  monitor_pod <name> [namespace]          - Real-time monitoring
  get_cluster_events [namespace] [lines]  - Get recent events

CLEANUP:
  cleanup_failed_pods [namespace]    - Remove failed pods
  cleanup_completed_jobs [namespace] - Remove completed jobs

USAGE:
  source k8s-troubleshooting-scripts.sh
  show_usage
EOF
}

# Show usage if script is run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    show_usage
fi

log_success "Troubleshooting scripts loaded. Run 'show_usage' for help."
