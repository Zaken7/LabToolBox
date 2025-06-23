#!/bin/bash
# Longhorn Node Management Toolkit
# Created: 2025-06-23
# Usage: ./longhorn-node-manager.sh [command] [options]

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
# LONGHORN NODE MANAGEMENT     #
#################################

# Show comprehensive node status
show_longhorn_nodes_status() {
    log_info "Displaying comprehensive Longhorn node status..."
    
    echo "=== KUBERNETES NODES ==="
    kubectl get nodes -o custom-columns="NAME:.metadata.name,STATUS:.status.conditions[?(@.type=='Ready')].status,ROLES:.metadata.labels.node-role\.kubernetes\.io/.*,AGE:.metadata.creationTimestamp,VERSION:.status.nodeInfo.kubeletVersion"
    
    echo -e "\n=== LONGHORN NODES OVERVIEW ==="
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,READY:.status.conditions[?(@.type=='Ready')].status,ALLOW_SCHEDULING:.spec.allowScheduling,SCHEDULABLE:.status.diskStatus.*.conditions[?(@.type=='Schedulable')].status"
    
    echo -e "\n=== LONGHORN NODE DETAILED STATUS ==="
    kubectl get nodes.longhorn.io -n longhorn-system -o wide
    
    echo -e "\n=== NODE STORAGE SUMMARY ==="
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,TOTAL_STORAGE:.status.diskStatus.*.storageMaximum,AVAILABLE:.status.diskStatus.*.storageAvailable,RESERVED:.spec.disks.*.storageReserved,SCHEDULED:.status.diskStatus.*.storageScheduled"
    
    echo -e "\n=== LONGHORN MANAGER PODS ON NODES ==="
    kubectl get pods -n longhorn-system -l app=longhorn-manager -o wide --sort-by=.spec.nodeName
}

# List nodes with scheduling enabled/disabled
list_scheduling_status() {
    log_info "Checking Longhorn node scheduling status..."
    
    echo "=== NODES WITH SCHEDULING ENABLED ==="
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,ALLOW_SCHEDULING:.spec.allowScheduling,SCHEDULABLE:.status.diskStatus.*.conditions[?(@.type=='Schedulable')].status" | grep -E "(true|True)"
    
    echo -e "\n=== NODES WITH SCHEDULING DISABLED ==="
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,ALLOW_SCHEDULING:.spec.allowScheduling,SCHEDULABLE:.status.diskStatus.*.conditions[?(@.type=='Schedulable')].status" | grep -E "(false|False)"
}

# Enable scheduling on specific nodes
enable_node_scheduling() {
    local nodes=("$@")
    
    if [[ ${#nodes[@]} -eq 0 ]]; then
        log_error "Usage: enable_node_scheduling <node1> [node2] [node3]..."
        log_info "Available nodes:"
        kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,ALLOW_SCHEDULING:.spec.allowScheduling" --no-headers
        return 1
    fi
    
    log_info "Enabling scheduling on nodes: ${nodes[*]}"
    
    for node in "${nodes[@]}"; do
        log_info "Enabling scheduling on $node..."
        
        # Check if node exists
        if ! kubectl get nodes.longhorn.io "$node" -n longhorn-system >/dev/null 2>&1; then
            log_error "Node $node not found in Longhorn"
            continue
        fi
        
        # Enable scheduling
        if kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p='{"spec":{"allowScheduling":true}}'; then
            log_success "Scheduling enabled on $node"
            
            # Also enable disk scheduling if disk exists
            local disk_id=$(kubectl get nodes.longhorn.io "$node" -n longhorn-system -o jsonpath='{.spec.disks}' | jq -r 'keys[0]' 2>/dev/null)
            if [[ -n "$disk_id" ]] && [[ "$disk_id" != "null" ]]; then
                kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p="{\"spec\":{\"disks\":{\"$disk_id\":{\"allowScheduling\":true}}}}" 2>/dev/null
                log_info "Disk scheduling also enabled on $node"
            fi
        else
            log_error "Failed to enable scheduling on $node"
        fi
    done
}

# Disable scheduling on specific nodes
disable_node_scheduling() {
    local nodes=("$@")
    
    if [[ ${#nodes[@]} -eq 0 ]]; then
        log_error "Usage: disable_node_scheduling <node1> [node2] [node3]..."
        log_info "Available nodes:"
        kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,ALLOW_SCHEDULING:.spec.allowScheduling" --no-headers
        return 1
    fi
    
    log_warning "Disabling scheduling on nodes: ${nodes[*]}"
    echo "This will prevent new volumes from being scheduled on these nodes. Continue? (y/N)"
    read -r response
    if [[ "$response" != "y" && "$response" != "Y" ]]; then
        log_info "Operation cancelled"
        return 0
    fi
    
    for node in "${nodes[@]}"; do
        log_info "Disabling scheduling on $node..."
        
        # Check if node exists
        if ! kubectl get nodes.longhorn.io "$node" -n longhorn-system >/dev/null 2>&1; then
            log_error "Node $node not found in Longhorn"
            continue
        fi
        
        # Disable scheduling
        if kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p='{"spec":{"allowScheduling":false}}'; then
            log_success "Scheduling disabled on $node"
            
            # Also disable disk scheduling if disk exists
            local disk_id=$(kubectl get nodes.longhorn.io "$node" -n longhorn-system -o jsonpath='{.spec.disks}' | jq -r 'keys[0]' 2>/dev/null)
            if [[ -n "$disk_id" ]] && [[ "$disk_id" != "null" ]]; then
                kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p="{\"spec\":{\"disks\":{\"$disk_id\":{\"allowScheduling\":false}}}}" 2>/dev/null
                log_info "Disk scheduling also disabled on $node"
            fi
        else
            log_error "Failed to disable scheduling on $node"
        fi
    done
}

# Configure data-only nodes (disable scheduling on control plane, enable on data nodes)
configure_data_only_nodes() {
    log_info "Configuring Longhorn to use only data nodes for storage..."
    
    # Get control plane nodes
    local control_nodes=($(kubectl get nodes -l node-role.kubernetes.io/control-plane -o jsonpath='{.items[*].metadata.name}'))
    
    # Get data nodes (nodes without control-plane label)
    local data_nodes=($(kubectl get nodes -l '!node-role.kubernetes.io/control-plane' -o jsonpath='{.items[*].metadata.name}'))
    
    echo "=== NODE CLASSIFICATION ==="
    echo "Control Plane Nodes: ${control_nodes[*]}"
    echo "Data Nodes: ${data_nodes[*]}"
    
    echo -e "\nThis will:"
    echo "- DISABLE scheduling on control plane nodes: ${control_nodes[*]}"
    echo "- ENABLE scheduling on data nodes: ${data_nodes[*]}"
    echo -e "\nContinue? (y/N)"
    read -r response
    if [[ "$response" != "y" && "$response" != "Y" ]]; then
        log_info "Operation cancelled"
        return 0
    fi
    
    # Disable scheduling on control plane nodes
    if [[ ${#control_nodes[@]} -gt 0 ]]; then
        log_info "Disabling storage scheduling on control plane nodes..."
        for node in "${control_nodes[@]}"; do
            if kubectl get nodes.longhorn.io "$node" -n longhorn-system >/dev/null 2>&1; then
                kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p='{"spec":{"allowScheduling":false}}'
                log_info "Disabled scheduling on $node"
            fi
        done
    fi
    
    # Enable scheduling on data nodes
    if [[ ${#data_nodes[@]} -gt 0 ]]; then
        log_info "Enabling storage scheduling on data nodes..."
        for node in "${data_nodes[@]}"; do
            if kubectl get nodes.longhorn.io "$node" -n longhorn-system >/dev/null 2>&1; then
                kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p='{"spec":{"allowScheduling":true}}'
                log_success "Enabled scheduling on $node"
            fi
        done
    fi
    
    log_success "Data-only node configuration completed"
}

# Show node disk usage and health
show_node_disk_status() {
    log_info "Displaying node disk status and health..."
    
    echo "=== NODE DISK HEALTH ==="
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,DISK_STATUS:.status.diskStatus.*.conditions[?(@.type=='Ready')].status,SCHEDULABLE:.status.diskStatus.*.conditions[?(@.type=='Schedulable')].status"
    
    echo -e "\n=== DETAILED DISK USAGE ==="
    local nodes=$(kubectl get nodes.longhorn.io -n longhorn-system -o jsonpath='{.items[*].metadata.name}')
    
    for node in $nodes; do
        echo -e "\n--- $node ---"
        local disk_info=$(kubectl get nodes.longhorn.io "$node" -n longhorn-system -o json)
        
        # Extract disk information using jq if available, otherwise use basic parsing
        if command -v jq >/dev/null 2>&1; then
            echo "$disk_info" | jq -r '
                .status.diskStatus // {} | to_entries[] | 
                "Disk: \(.key)",
                "  Path: \(.value.diskPath // "N/A")",
                "  Total: \((.value.storageMaximum // 0) / 1024 / 1024 / 1024 | floor)GB",
                "  Available: \((.value.storageAvailable // 0) / 1024 / 1024 / 1024 | floor)GB",
                "  Scheduled: \((.value.storageScheduled // 0) / 1024 / 1024 / 1024 | floor)GB",
                "  Usage: \((100 - ((.value.storageAvailable // 0) * 100 / (.value.storageMaximum // 1))) | floor)%"
            ' 2>/dev/null || echo "  Disk information available (install jq for detailed view)"
        else
            # Basic parsing without jq
            echo "  $(echo "$disk_info" | grep -o '"storageMaximum":[0-9]*' | head -1 | cut -d: -f2 | awk '{print int($1/1024/1024/1024)"GB total"}' || echo "Disk info available")"
        fi
    done
}

# Drain node (move replicas away before maintenance)
drain_longhorn_node() {
    local node="$1"
    local force="${2:-false}"
    
    if [[ -z "$node" ]]; then
        log_error "Usage: drain_longhorn_node <node_name> [force]"
        log_info "Available nodes:"
        kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,READY:.status.conditions[?(@.type=='Ready')].status" --no-headers
        return 1
    fi
    
    log_warning "Draining Longhorn node: $node"
    echo "This will move all replicas away from $node. This may take time."
    
    if [[ "$force" != "force" ]]; then
        echo "Continue? (y/N)"
        read -r response
        if [[ "$response" != "y" && "$response" != "Y" ]]; then
            log_info "Operation cancelled"
            return 0
        fi
    fi
    
    # Check if node exists
    if ! kubectl get nodes.longhorn.io "$node" -n longhorn-system >/dev/null 2>&1; then
        log_error "Node $node not found in Longhorn"
        return 1
    fi
    
    # Disable scheduling first
    log_info "Step 1: Disabling scheduling on $node..."
    kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p='{"spec":{"allowScheduling":false}}'
    
    # Get replicas on this node
    log_info "Step 2: Finding replicas on $node..."
    local replicas=$(kubectl get replicas.longhorn.io -n longhorn-system -o json | jq -r ".items[] | select(.spec.nodeID == \"$node\") | .metadata.name" 2>/dev/null || echo "")
    
    if [[ -z "$replicas" ]]; then
        log_info "No replicas found on $node"
    else
        log_info "Found replicas on $node:"
        echo "$replicas"
        
        log_info "Step 3: Waiting for replicas to be moved away..."
        log_info "This may take several minutes depending on data size..."
        
        # Monitor replica movement
        local timeout=1800  # 30 minutes
        local elapsed=0
        
        while [[ $elapsed -lt $timeout ]]; do
            local current_replicas=$(kubectl get replicas.longhorn.io -n longhorn-system -o json | jq -r ".items[] | select(.spec.nodeID == \"$node\") | .metadata.name" 2>/dev/null | wc -l)
            
            if [[ "$current_replicas" -eq 0 ]]; then
                log_success "All replicas moved away from $node"
                break
            fi
            
            echo -n "."
            sleep 30
            elapsed=$((elapsed + 30))
        done
        
        if [[ $elapsed -ge $timeout ]]; then
            log_warning "Timeout waiting for replicas to move. Some replicas may still be on $node"
        fi
    fi
    
    log_success "Node $node has been drained"
    log_info "You can now safely perform maintenance on this node"
}

# Uncordon node (re-enable scheduling after maintenance)
uncordon_longhorn_node() {
    local node="$1"
    
    if [[ -z "$node" ]]; then
        log_error "Usage: uncordon_longhorn_node <node_name>"
        log_info "Available nodes:"
        kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,ALLOW_SCHEDULING:.spec.allowScheduling" --no-headers
        return 1
    fi
    
    log_info "Uncordoning Longhorn node: $node"
    
    # Check if node exists
    if ! kubectl get nodes.longhorn.io "$node" -n longhorn-system >/dev/null 2>&1; then
        log_error "Node $node not found in Longhorn"
        return 1
    fi
    
    # Re-enable scheduling
    if kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p='{"spec":{"allowScheduling":true}}'; then
        log_success "Scheduling re-enabled on $node"
        
        # Also enable disk scheduling
        local disk_id=$(kubectl get nodes.longhorn.io "$node" -n longhorn-system -o jsonpath='{.spec.disks}' | jq -r 'keys[0]' 2>/dev/null)
        if [[ -n "$disk_id" ]] && [[ "$disk_id" != "null" ]]; then
            kubectl patch nodes.longhorn.io "$node" -n longhorn-system --type='merge' -p="{\"spec\":{\"disks\":{\"$disk_id\":{\"allowScheduling\":true}}}}" 2>/dev/null
            log_info "Disk scheduling also enabled"
        fi
        
        log_success "Node $node is ready for scheduling"
    else
        log_error "Failed to uncordon $node"
        return 1
    fi
}

# Check node connectivity and health
check_node_connectivity() {
    log_info "Checking Longhorn node connectivity and health..."
    
    echo "=== LONGHORN MANAGER POD STATUS ==="
    kubectl get pods -n longhorn-system -l app=longhorn-manager -o wide
    
    echo -e "\n=== NODE READINESS ==="
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,READY:.status.conditions[?(@.type=='Ready')].status,LAST_SEEN:.status.conditions[?(@.type=='Ready')].lastTransitionTime"
    
    echo -e "\n=== INSTANCE MANAGERS ==="
    kubectl get pods -n longhorn-system | grep instance-manager
    
    echo -e "\n=== NODE LABELS ==="
    kubectl get nodes --show-labels | grep longhorn
}

# Show nodes that need attention
show_problem_nodes() {
    log_info "Identifying Longhorn nodes that need attention..."
    
    echo "=== NODES WITH ISSUES ==="
    
    # Nodes with scheduling disabled
    echo -e "\n--- Nodes with Scheduling Disabled ---"
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,ALLOW_SCHEDULING:.spec.allowScheduling" --no-headers | grep false || echo "None"
    
    # Nodes not ready
    echo -e "\n--- Nodes Not Ready ---"
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,READY:.status.conditions[?(@.type=='Ready')].status" --no-headers | grep -v True || echo "None"
    
    # Nodes with failed manager pods
    echo -e "\n--- Nodes with Failed Manager Pods ---"
    kubectl get pods -n longhorn-system -l app=longhorn-manager --no-headers | grep -v Running || echo "None"
    
    # Nodes with disk issues
    echo -e "\n--- Nodes with Disk Issues ---"
    kubectl get nodes.longhorn.io -n longhorn-system -o custom-columns="NODE:.metadata.name,DISK_SCHEDULABLE:.status.diskStatus.*.conditions[?(@.type=='Schedulable')].status" --no-headers | grep False || echo "None"
}

# Optimize node configuration
optimize_node_configuration() {
    log_info "Optimizing Longhorn node configuration..."
    
    echo "This will:"
    echo "- Configure data-only scheduling (disable on control plane)"
    echo "- Set optimal replica count to 2"
    echo "- Adjust storage reservation to 20%"
    echo -e "\nContinue? (y/N)"
    read -r response
    if [[ "$response" != "y" && "$response" != "Y" ]]; then
        log_info "Optimization cancelled"
        return 0
    fi
    
    # Configure data-only nodes
    log_info "Step 1: Configuring data-only node scheduling..."
    configure_data_only_nodes
    
    # Set replica count
    log_info "Step 2: Setting default replica count to 2..."
    kubectl patch settings.longhorn.io default-replica-count -n longhorn-system --type='merge' -p='{"value":"2"}'
    
    # Set storage reservation
    log_info "Step 3: Setting storage reservation to 20%..."
    kubectl patch settings.longhorn.io storage-reserved-percentage-for-default-disk -n longhorn-system --type='merge' -p='{"value":"20"}'
    
    log_success "Node configuration optimization completed"
}

# Show usage
show_usage() {
    cat << 'EOFUSAGE'
Longhorn Node Management Toolkit

NODE STATUS COMMANDS:
  show_longhorn_nodes_status      - Comprehensive node status overview
  list_scheduling_status          - Show scheduling enabled/disabled nodes
  show_node_disk_status          - Display disk usage and health
  check_node_connectivity        - Check node connectivity and health
  show_problem_nodes             - Identify nodes needing attention

NODE SCHEDULING COMMANDS:
  enable_node_scheduling <nodes>  - Enable scheduling on specific nodes
  disable_node_scheduling <nodes> - Disable scheduling on specific nodes
  configure_data_only_nodes       - Configure data-only scheduling
  optimize_node_configuration     - Optimize overall node configuration

NODE MAINTENANCE COMMANDS:
  drain_longhorn_node <node>      - Drain node for maintenance
  uncordon_longhorn_node <node>   - Re-enable node after maintenance

EXAMPLES:
  # Check overall status
  ./longhorn-node-manager.sh show_longhorn_nodes_status
  
  # Manage scheduling
  ./longhorn-node-manager.sh disable_node_scheduling test-k3s-04 test-k3s-05
  ./longhorn-node-manager.sh enable_node_scheduling test-k3s-data-01
  
  # Node maintenance
  ./longhorn-node-manager.sh drain_longhorn_node test-k3s-data-02
  ./longhorn-node-manager.sh uncordon_longhorn_node test-k3s-data-02
  
  # Configuration
  ./longhorn-node-manager.sh configure_data_only_nodes
  ./longhorn-node-manager.sh optimize_node_configuration

WORKFLOW FOR NODE MAINTENANCE:
  1. drain_longhorn_node <node>     # Move replicas away
  2. Perform maintenance on node
  3. uncordon_longhorn_node <node>  # Re-enable scheduling

EOFUSAGE
}

# Main execution
main() {
    case "${1:-}" in
        "show_longhorn_nodes_status"|"status")
            show_longhorn_nodes_status
            ;;
        "list_scheduling_status"|"scheduling")
            list_scheduling_status
            ;;
        "enable_node_scheduling"|"enable")
            shift
            enable_node_scheduling "$@"
            ;;
        "disable_node_scheduling"|"disable")
            shift
            disable_node_scheduling "$@"
            ;;
        "configure_data_only_nodes"|"data-only")
            configure_data_only_nodes
            ;;
        "show_node_disk_status"|"disks")
            show_node_disk_status
            ;;
        "drain_longhorn_node"|"drain")
            drain_longhorn_node "$2" "$3"
            ;;
        "uncordon_longhorn_node"|"uncordon")
            uncordon_longhorn_node "$2"
            ;;
        "check_node_connectivity"|"connectivity")
            check_node_connectivity
            ;;
        "show_problem_nodes"|"problems")
            show_problem_nodes
            ;;
        "optimize_node_configuration"|"optimize")
            optimize_node_configuration
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
