#!/bin/bash
# Enhanced SSH Node Troubleshooting with Automation
# Created: 2025-06-23
# Usage: ./ssh-fix-automation.sh [command] [options]

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

# Enhanced Fix SSH access with automation
fix_ssh_nodes_auto() {
    log_info "Enhanced SSH connectivity check with automation..."
    
    local failed_nodes=()
    local working_nodes=()
    
    # Get nodes from kubectl if available, otherwise use common IPs
    local nodes
    if command -v kubectl >/dev/null 2>&1; then
        nodes=$(kubectl get nodes -o wide --no-headers 2>/dev/null | awk '{print $6}' | grep -E '^192\.168\.' || echo "")
    fi
    
    # If no kubectl or no nodes found, use common cluster IPs
    if [[ -z "$nodes" ]]; then
        nodes="192.168.145.110 192.168.145.111 192.168.145.112 192.168.145.113 192.168.145.114"
        log_info "Using default cluster IP range for testing"
    fi
    
    # Test each node
    echo "=== ENHANCED SSH CONNECTIVITY TEST ==="
    for ip in $nodes; do
        echo -n "Testing $ip: "
        if timeout 5 ssh -o BatchMode=yes -o ConnectTimeout=3 ubuntu@"$ip" "echo 'ok'" >/dev/null 2>&1; then
            echo -e "${GREEN}SUCCESS${NC}"
            working_nodes+=("$ip")
        else
            echo -e "${RED}FAILED${NC}"
            failed_nodes+=("$ip")
        fi
    done
    
    if [[ ${#failed_nodes[@]} -eq 0 ]]; then
        log_success "All nodes are accessible via SSH"
        return 0
    fi
    
    echo ""
    log_warning "Found ${#failed_nodes[@]} failed nodes: ${failed_nodes[*]}"
    log_info "Working nodes: ${working_nodes[*]}"
    
    # Check available public keys
    local available_keys=()
    local key_files=()
    
    if [[ -f ~/.ssh/kube.pub ]]; then
        available_keys+=("kube.pub ($(head -c 30 ~/.ssh/kube.pub)...)")
        key_files+=("$HOME/.ssh/kube.pub")
    fi
    if [[ -f ~/.ssh/id_rsa.pub ]]; then
        available_keys+=("id_rsa.pub ($(head -c 30 ~/.ssh/id_rsa.pub)...)")
        key_files+=("$HOME/.ssh/id_rsa.pub")
    fi
    if [[ -f ~/.ssh/id_ed25519.pub ]]; then
        available_keys+=("id_ed25519.pub ($(head -c 30 ~/.ssh/id_ed25519.pub)...)")
        key_files+=("$HOME/.ssh/id_ed25519.pub")
    fi
    
    if [[ ${#available_keys[@]} -eq 0 ]]; then
        log_error "No public keys found in ~/.ssh/"
        log_info "Generate a key first: ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519"
        return 1
    fi
    
    # Let user select which key to use
    echo -e "\nAvailable SSH public keys:"
    for i in "${!available_keys[@]}"; do
        echo "  $((i+1)). ${available_keys[$i]}"
    done
    
    echo -e "\nSelect which public key to deploy (1-${#available_keys[@]}, or 'q' to quit): "
    read -r key_choice
    
    if [[ "$key_choice" == "q" || "$key_choice" == "Q" ]]; then
        log_info "SSH fix cancelled"
        return 0
    fi
    
    if ! [[ "$key_choice" =~ ^[0-9]+$ ]] || [[ "$key_choice" -lt 1 ]] || [[ "$key_choice" -gt ${#available_keys[@]} ]]; then
        log_error "Invalid selection"
        return 1
    fi
    
    local selected_key_file="${key_files[$((key_choice-1))]}"
    local selected_key_content=$(cat "$selected_key_file")
    
    log_info "Selected key: ${available_keys[$((key_choice-1))]}"
    
    # Choose deployment method
    echo -e "\nChoose deployment method:"
    echo "  1. Smart automation (tests connectivity and auto-deploys)"
    echo "  2. Password authentication only"
    echo "  3. Manual instructions only"
    echo -e "\nSelect method (1-3): "
    read -r method_choice
    
    case "$method_choice" in
        "1")
            smart_ssh_deployment "${failed_nodes[@]}" "$selected_key_content" "$selected_key_file"
            ;;
        "2")
            password_ssh_deployment "${failed_nodes[@]}" "$selected_key_file"
            ;;
        "3")
            manual_ssh_instructions "${failed_nodes[@]}" "$selected_key_content"
            ;;
        *)
            log_error "Invalid selection"
            return 1
            ;;
    esac
}

# Smart SSH deployment with automated testing
smart_ssh_deployment() {
    local failed_nodes=("$@")
    local key_content="${@: -2:1}"    # Second to last argument
    local key_file="${@: -1}"         # Last argument
    failed_nodes=("${@:1:$(($#-2))}")  # All but last two arguments
    
    log_info "Starting smart SSH deployment..."
    
    for failed_ip in "${failed_nodes[@]}"; do
        echo ""
        echo "========================================"
        log_info "Processing $failed_ip"
        echo "========================================"
        
        # Test 1: Network connectivity
        echo -n "Network connectivity: "
        if ! ping -c 1 -W 3 "$failed_ip" >/dev/null 2>&1; then
            echo -e "${RED}FAIL${NC}"
            log_error "$failed_ip is unreachable - check if server is powered on"
            continue
        fi
        echo -e "${GREEN}PASS${NC}"
        
        # Test 2: SSH port accessibility  
        echo -n "SSH port 22: "
        if ! timeout 3 bash -c "</dev/tcp/$failed_ip/22" 2>/dev/null; then
            echo -e "${RED}FAIL${NC}"
            log_error "$failed_ip SSH port not accessible - check SSH service and firewall"
            continue
        fi
        echo -e "${GREEN}PASS${NC}"
        
        # Both tests passed - attempt automated deployment
        log_success "Both connectivity tests passed! Attempting automated key deployment..."
        
        # Try password authentication first (most likely to work)
        echo ""
        log_info "Attempting automatic SSH key deployment via password authentication..."
        echo "Enter password for ubuntu@$failed_ip (or press Ctrl+C to skip to manual):"
        
        # Try ssh-copy-id with password auth
        if ssh-copy-id -f -o PreferredAuthentications=password -o PubkeyAuthentication=no -i "$key_file" ubuntu@"$failed_ip" 2>/dev/null; then
            log_success "SSH key automatically deployed to $failed_ip!"
            
            # Test the new connection
            if ssh -o ConnectTimeout=5 ubuntu@"$failed_ip" "echo 'SSH connection test successful'" 2>/dev/null; then
                log_success "SSH connection to $failed_ip verified and working!"
                continue
            else
                log_warning "Key deployed but connection test failed"
            fi
        else
            log_info "Password authentication not available or failed - providing manual instructions"
        fi
        
        # If automated deployment failed, provide manual instructions
        provide_smart_manual_instructions "$failed_ip" "$key_content"
    done
}

# Password-based SSH deployment
password_ssh_deployment() {
    local failed_nodes=("$@")
    local key_file="${@: -1}"  # Last argument is key file
    failed_nodes=("${@:1:$(($#-1))}")  # All but last argument
    
    log_info "Attempting deployment using password authentication..."
    
    for ip in "${failed_nodes[@]}"; do
        echo ""
        log_info "Processing $ip with password authentication..."
        
        # Quick connectivity check
        if ! ping -c 1 -W 3 "$ip" >/dev/null 2>&1; then
            log_error "$ip: Network unreachable"
            continue
        fi
        
        if ! timeout 3 bash -c "</dev/tcp/$ip/22" 2>/dev/null; then
            log_error "$ip: SSH port not accessible"
            continue
        fi
        
        log_info "Both connectivity tests passed - attempting password deployment..."
        echo "Enter password for ubuntu@$ip:"
        
        if ssh-copy-id -f -o PreferredAuthentications=password -o PubkeyAuthentication=no -i "$key_file" ubuntu@"$ip"; then
            log_success "SSH key deployed to $ip successfully"
            
            # Test the connection
            if ssh -o ConnectTimeout=5 ubuntu@"$ip" "echo 'SSH test successful'"; then
                log_success "SSH connection verified for $ip"
            fi
        else
            log_warning "Password authentication failed for $ip"
            provide_smart_manual_instructions "$ip" "$(cat "$key_file")"
        fi
    done
}

# Manual instructions optimized for copy-paste
manual_ssh_instructions() {
    local failed_nodes=("$@")
    local key_content="${@: -1}"  # Last argument is key content
    failed_nodes=("${@:1:$(($#-1))}")  # All but last argument
    
    for ip in "${failed_nodes[@]}"; do
        provide_smart_manual_instructions "$ip" "$key_content"
    done
}

# Smart manual instructions with automated command generation
provide_smart_manual_instructions() {
    local target_ip="$1"
    local key_content="$2"
    
    echo ""
    echo "========================================"
    log_info "Manual fix for $target_ip"
    echo "========================================"
    
    # Quick diagnostics
    echo -n "Network: "
    if ping -c 1 -W 3 "$target_ip" >/dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC}"
    else
        echo -e "${RED}FAIL${NC} - Server may be down"
        return 1
    fi
    
    echo -n "SSH Port: "
    if timeout 3 bash -c "</dev/tcp/$target_ip/22" 2>/dev/null; then
        echo -e "${GREEN}PASS${NC}"
    else
        echo -e "${RED}FAIL${NC} - SSH service issue"
        return 1
    fi
    
    echo ""
    log_success "Connectivity tests passed! Ready for automated commands."
    echo ""
    log_warning "Copy and paste these commands on $target_ip console:"
    echo ""
    echo "# === AUTOMATED SSH SETUP COMMANDS ==="
    echo ""
    echo "# Single command (copy this entire line):"
    echo "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$key_content' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && chown -R \$(whoami):\$(whoami) ~/.ssh && echo 'SSH setup complete!'"
    echo ""
    echo "# OR run step by step:"
    echo "mkdir -p ~/.ssh"
    echo "chmod 700 ~/.ssh"
    echo "echo '$key_content' >> ~/.ssh/authorized_keys"
    echo "chmod 600 ~/.ssh/authorized_keys" 
    echo "chown -R \$(whoami):\$(whoami) ~/.ssh"
    echo "ls -la ~/.ssh/"
    echo "echo 'Setup complete - try SSH connection now'"
    echo ""
    echo "# === END OF COMMANDS ==="
    echo ""
    echo "Access methods:"
    echo "  • Hypervisor console (VMware/VirtualBox/Proxmox)"
    echo "  • Cloud provider web console (AWS/Azure/GCP)"
    echo "  • IPMI/iDRAC/iLO for physical servers"
    echo ""
}

# Quick SSH test function
test_ssh_fixed() {
    local target_ip="$1"
    
    if [[ -z "$target_ip" ]]; then
        log_error "Usage: test_ssh_fixed <ip>"
        return 1
    fi
    
    log_info "Testing SSH connection to $target_ip..."
    
    if ssh -o ConnectTimeout=5 ubuntu@"$target_ip" "echo 'SSH connection successful to $target_ip'"; then
        log_success "SSH connection to $target_ip is working!"
        return 0
    else
        log_error "SSH connection to $target_ip failed"
        return 1
    fi
}

# Show usage
show_usage() {
    cat << 'EOFUSAGE'
Enhanced SSH Troubleshooting with Automation

COMMANDS:
  fix_ssh_nodes_auto               - Enhanced SSH fix with smart automation
  test_ssh_fixed <ip>              - Test if SSH is working after fix
  
FEATURES:
  • Automatic SSH key selection
  • Smart connectivity testing  
  • Automated password deployment
  • Copy-paste ready manual commands
  • Real-time verification

EXAMPLES:
  ./ssh-fix-automation.sh fix_ssh_nodes_auto
  ./ssh-fix-automation.sh test_ssh_fixed 192.168.145.112

EOFUSAGE
}

# Main execution
main() {
    case "${1:-}" in
        "fix_ssh_nodes_auto"|"fix")
            fix_ssh_nodes_auto
            ;;
        "test_ssh_fixed"|"test") 
            test_ssh_fixed "$2"
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
