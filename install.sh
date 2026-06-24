#!/bin/bash
# /usr/local/bin/network-recover
# Production-Grade Linux Network Recovery Engine
# Version: 1.0.0
# License: MIT
#
# Usage:
#   sudo network-recover diagnose   - Run full diagnostic (no changes)
#   sudo network-recover repair     - Diagnose and attempt repairs
#   sudo network-recover snapshot   - Save current network state
#   sudo network-recover watch      - Monitor network health in real-time
#
# Supports: Debian, Ubuntu, Fedora, Arch, MX Linux, RHEL, etc.

set -euo pipefail

# ============================================================
# CONFIGURATION
# ============================================================

readonly VERSION="1.0.0"
readonly SCRIPT_NAME="network-recover"

# Directories
readonly LOG_DIR="/var/log/network-events"
readonly SNAPSHOT_DIR="/var/lib/network-recover/snapshots"
readonly TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)

# Test targets (multiple for redundancy)
readonly IP_TARGETS=("1.1.1.1" "8.8.8.8" "9.9.9.9")
readonly HTTPS_TARGETS=(
    "https://cloudflare.com"
    "https://google.com"
    "https://github.com"
    "https://microsoft.com"
)
readonly DNS_TARGETS=("google.com" "cloudflare.com" "github.com")
readonly CAPTIVE_PORTAL_TEST="http://connectivitycheck.gstatic.com/generate_204"

# Timeouts
readonly PING_TIMEOUT=2
readonly CURL_TIMEOUT=5
readonly DNS_TIMEOUT=3

# ============================================================
# INITIALIZATION
# ============================================================

mkdir -p "$LOG_DIR" "$SNAPSHOT_DIR"

# Determine the default interface dynamically
DEFAULT_IFACE=$(ip route | awk '/default/ {print $5; exit}' 2>/dev/null || echo "eth0")
DEFAULT_GATEWAY=$(ip route | awk '/default/ {print $3; exit}' 2>/dev/null || echo "")

# Detect if we have a bridge
BRIDGE_IFACE=""
for iface in $(ip link show | grep -oP '(?<=: )\w+(?=:)' | grep -v lo); do
    if ip link show "$iface" | grep -q "bridge"; then
        BRIDGE_IFACE="$iface"
        break
    fi
done

# Detect virtualization
HAS_LIBVIRT=$(command -v virsh &>/dev/null && echo "true" || echo "false")
HAS_KUBECTL=$(command -v kubectl &>/dev/null && echo "true" || echo "false")
HAS_DOCKER=$(command -v docker &>/dev/null && echo "true" || echo "false")

# ============================================================
# HELPERS
# ============================================================

log() {
    local level="${1:-INFO}"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
}

log_result() {
    local status="$1"
    local message="$2"
    if [[ "$status" == "PASS" ]]; then
        echo -e "  ✅ $message"
    elif [[ "$status" == "FAIL" ]]; then
        echo -e "  ❌ $message"
    elif [[ "$status" == "WARN" ]]; then
        echo -e "  ⚠️  $message"
    elif [[ "$status" == "INFO" ]]; then
        echo -e "  ℹ️  $message"
    else
        echo "  $message"
    fi
}

save_snapshot() {
    local snapshot_file="$SNAPSHOT_DIR/snapshot-${TIMESTAMP}.log"
    {
        echo "=== NETWORK SNAPSHOT: $TIMESTAMP ==="
        echo "=== System Info ==="
        uname -a
        cat /etc/os-release 2>/dev/null || echo "No os-release"
        echo ""
        echo "=== Interface Info ==="
        ip addr show
        echo ""
        echo "=== Route Table ==="
        ip route show
        echo ""
        echo "=== ARP Table ==="
        ip neigh show
        echo ""
        echo "=== Bridge Info ==="
        bridge link show 2>/dev/null || echo "No bridges found"
        echo ""
        echo "=== NetworkManager Status ==="
        nmcli general status 2>/dev/null || echo "NetworkManager not available"
        nmcli device status 2>/dev/null || echo ""
        echo ""
        echo "=== DNS Configuration ==="
        cat /etc/resolv.conf 2>/dev/null || echo "No resolv.conf"
        resolvectl status 2>/dev/null || echo "resolvectl not available"
        echo ""
        echo "=== Active Connections ==="
        ss -tulpn 2>/dev/null | head -50
        echo ""
        echo "=== Recent Network Logs ==="
        journalctl -u NetworkManager -n 50 --no-pager 2>/dev/null || echo "No NetworkManager logs"
        echo ""
        echo "=== Kernel Network Stats ==="
        cat /proc/net/dev
        echo ""
        echo "=== End Snapshot ==="
    } > "$snapshot_file"
    echo "$snapshot_file"
}

# ============================================================
# LAYER 1: PHYSICAL LAYER
# ============================================================

check_physical() {
    log "INFO" "=== LAYER 1: PHYSICAL ==="
    local all_pass=true
    
    # Check if interface exists
    if [[ ! -d "/sys/class/net/$DEFAULT_IFACE" ]]; then
        log_result "FAIL" "Interface $DEFAULT_IFACE does not exist"
        return 1
    fi
    
    # Check carrier
    if [[ -f "/sys/class/net/$DEFAULT_IFACE/carrier" ]]; then
        local carrier=$(cat "/sys/class/net/$DEFAULT_IFACE/carrier")
        if [[ "$carrier" == "1" ]]; then
            log_result "PASS" "Carrier: present"
        else
            log_result "FAIL" "Carrier: LOST - Check cable/WiFi"
            all_pass=false
        fi
    fi
    
    # Check operstate
    if [[ -f "/sys/class/net/$DEFAULT_IFACE/operstate" ]]; then
        local state=$(cat "/sys/class/net/$DEFAULT_IFACE/operstate")
        if [[ "$state" == "up" ]]; then
            log_result "PASS" "Interface state: $state"
        else
            log_result "FAIL" "Interface state: $state (should be up)"
            all_pass=false
        fi
    fi
    
    # Check speed and duplex (ethernet only)
    if command -v ethtool &>/dev/null && [[ -e "/sys/class/net/$DEFAULT_IFACE/device" ]]; then
        local speed=$(ethtool "$DEFAULT_IFACE" 2>/dev/null | grep -i "Speed:" | awk '{print $2}')
        local duplex=$(ethtool "$DEFAULT_IFACE" 2>/dev/null | grep -i "Duplex:" | awk '{print $2}')
        if [[ -n "$speed" ]]; then
            log_result "INFO" "Speed: $speed, Duplex: $duplex"
        fi
    fi
    
    if [[ "$all_pass" == "true" ]]; then
        return 0
    else
        return 1
    fi
}

# ============================================================
# LAYER 2: LINK LAYER (Bridge, Bond, VLAN)
# ============================================================

check_link_layer() {
    log "INFO" "=== LAYER 2: LINK LAYER ==="
    local all_pass=true
    
    # Check if interface is UP
    if ip link show "$DEFAULT_IFACE" | grep -q "UP"; then
        log_result "PASS" "Interface $DEFAULT_IFACE is UP"
    else
        log_result "FAIL" "Interface $DEFAULT_IFACE is DOWN"
        all_pass=false
    fi
    
    # Check bridge if present
    if [[ -n "$BRIDGE_IFACE" ]]; then
        if ip link show "$BRIDGE_IFACE" | grep -q "UP"; then
            log_result "PASS" "Bridge $BRIDGE_IFACE is UP"
        else
            log_result "FAIL" "Bridge $BRIDGE_IFACE is DOWN"
            all_pass=false
        fi
        
        # Check if interface is enslaved to bridge
        if bridge link show "$BRIDGE_IFACE" 2>/dev/null | grep -q "$DEFAULT_IFACE"; then
            log_result "PASS" "$DEFAULT_IFACE enslaved to $BRIDGE_IFACE"
        else
            log_result "WARN" "$DEFAULT_IFACE NOT enslaved to $BRIDGE_IFACE"
            all_pass=false
        fi
    fi
    
    # Check for vnet interfaces (KVM)
    if [[ "$HAS_LIBVIRT" == "true" ]]; then
        local vnets=$(ip link show | grep -oP 'vnet\d+' | sort -u)
        if [[ -n "$vnets" ]]; then
            for vnet in $vnets; do
                if bridge link show 2>/dev/null | grep -q "$vnet"; then
                    log_result "PASS" "$vnet is bridged"
                else
                    log_result "WARN" "$vnet NOT bridged"
                    all_pass=false
                fi
            done
        fi
    fi
    
    [[ "$all_pass" == "true" ]] && return 0 || return 1
}

# ============================================================
# LAYER 3: IP LAYER
# ============================================================

check_ip_layer() {
    log "INFO" "=== LAYER 3: IP ==="
    local all_pass=true
    
    # Check IPv4 address
    local iface_to_check="${BRIDGE_IFACE:-$DEFAULT_IFACE}"
    local ipv4=$(ip -4 addr show "$iface_to_check" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}/\d+' | head -1)
    
    if [[ -n "$ipv4" ]]; then
        log_result "PASS" "IPv4: $ipv4"
        
        # Check for duplicate IP
        local ip_only=$(echo "$ipv4" | cut -d/ -f1)
        if arping -c 1 -I "$iface_to_check" "$ip_only" 2>/dev/null | grep -q "reply from"; then
            log_result "WARN" "Possible duplicate IP detected!"
        fi
    else
        log_result "FAIL" "No IPv4 address on $iface_to_check"
        all_pass=false
    fi
    
    # Check IPv6
    local ipv6=$(ip -6 addr show "$iface_to_check" 2>/dev/null | grep -oP '(?<=inet6\s)[a-f0-9:]+' | grep -v "^::1" | head -1)
    if [[ -n "$ipv6" ]]; then
        log_result "INFO" "IPv6: $ipv6"
    else
        log_result "INFO" "No IPv6 address (may be disabled)"
    fi
    
    [[ "$all_pass" == "true" ]] && return 0 || return 1
}

# ============================================================
# LAYER 4: ROUTING
# ============================================================

check_routing() {
    log "INFO" "=== LAYER 4: ROUTING ==="
    local all_pass=true
    
    # Check default route
    if [[ -n "$DEFAULT_GATEWAY" ]]; then
        log_result "PASS" "Default gateway: $DEFAULT_GATEWAY"
    else
        log_result "FAIL" "No default route found"
        return 1
    fi
    
    # Check for multiple default routes (common problem)
    local default_count=$(ip route | grep -c "^default")
    if [[ "$default_count" -gt 1 ]]; then
        log_result "WARN" "Multiple default routes found ($default_count)"
        ip route | grep "^default"
        all_pass=false
    fi
    
    # Check for blackhole routes
    if ip route | grep -q "blackhole"; then
        log_result "WARN" "Blackhole routes detected"
        ip route | grep "blackhole"
        all_pass=false
    fi
    
    # Check route metrics
    if ip route | grep -q "metric"; then
        log_result "INFO" "Route metrics configured"
    fi
    
    [[ "$all_pass" == "true" ]] && return 0 || return 1
}

# ============================================================
# LAYER 5: GATEWAY
# ============================================================

check_gateway() {
    log "INFO" "=== LAYER 5: GATEWAY ==="
    
    if [[ -z "$DEFAULT_GATEWAY" ]]; then
        log_result "FAIL" "No default gateway - skipping gateway checks"
        return 1
    fi
    
    local all_pass=true
    
    # Check ARP entry
    if ip neigh show "$DEFAULT_GATEWAY" | grep -q "REACHABLE"; then
        log_result "PASS" "Gateway ARP: REACHABLE"
    elif ip neigh show "$DEFAULT_GATEWAY" | grep -q "STALE"; then
        log_result "WARN" "Gateway ARP: STALE - may need refresh"
        all_pass=false
    else
        log_result "WARN" "No ARP entry for gateway"
        all_pass=false
    fi
    
    # Ping gateway with short timeout
    if ping -c 1 -W "$PING_TIMEOUT" "$DEFAULT_GATEWAY" &>/dev/null; then
        log_result "PASS" "Gateway reachable (ICMP)"
    else
        # Try ARP ping
        if arping -c 1 -W 1 "$DEFAULT_GATEWAY" &>/dev/null; then
            log_result "WARN" "Gateway responds to ARP but not ICMP"
        else
            log_result "FAIL" "Gateway unreachable"
            all_pass=false
        fi
    fi
    
    [[ "$all_pass" == "true" ]] && return 0 || return 1
}

# ============================================================
# LAYER 6: INTERNET REACHABILITY
# ============================================================

check_internet() {
    log "INFO" "=== LAYER 6: INTERNET REACHABILITY ==="
    local reachable_count=0
    local total_targets=${#IP_TARGETS[@]}
    
    for target in "${IP_TARGETS[@]}"; do
        if ping -c 1 -W "$PING_TIMEOUT" "$target" &>/dev/null; then
            log_result "PASS" "$target reachable (ICMP)"
            ((reachable_count++))
        else
            # Try TCP connect as fallback
            if command -v nc &>/dev/null && nc -zv -w 3 "$target" 443 &>/dev/null 2>&1; then
                log_result "PASS" "$target reachable (TCP/443)"
                ((reachable_count++))
            else
                log_result "WARN" "$target unreachable"
            fi
        fi
    done
    
    # Require quorum (at least 2 out of 3)
    if [[ "$reachable_count" -ge 2 ]]; then
        log_result "PASS" "Internet reachable ($reachable_count/$total_targets)"
        return 0
    else
        log_result "FAIL" "Internet unreachable ($reachable_count/$total_targets)"
        return 1
    fi
}

# ============================================================
# LAYER 7: DNS
# ============================================================

check_dns() {
    log "INFO" "=== LAYER 7: DNS ==="
    local all_pass=true
    
    # Check resolv.conf
    if [[ -f /etc/resolv.conf ]]; then
        local nameservers=$(grep "^nameserver" /etc/resolv.conf | wc -l)
        if [[ "$nameservers" -gt 0 ]]; then
            log_result "PASS" "DNS servers configured ($nameservers)"
            grep "^nameserver" /etc/resolv.conf | while read -r line; do
                log_result "INFO" "  $line"
            done
        else
            log_result "FAIL" "No nameservers in /etc/resolv.conf"
            all_pass=false
        fi
    fi
    
    # Test DNS resolution with multiple servers
    local dns_success=0
    for domain in "${DNS_TARGETS[@]}"; do
        if nslookup "$domain" &>/dev/null; then
            log_result "PASS" "$domain resolves"
            ((dns_success++))
        else
            # Try with specific DNS server
            if dig "@1.1.1.1" "$domain" +timeout=2 &>/dev/null; then
                log_result "PASS" "$domain resolves (via 1.1.1.1)"
                ((dns_success++))
            else
                log_result "WARN" "$domain resolution failed"
            fi
        fi
    done
    
    # Check for DNS poisoning
    if command -v dig &>/dev/null; then
        local ip1=$(dig "@1.1.1.1" google.com +short 2>/dev/null | head -1)
        local ip2=$(dig "@8.8.8.8" google.com +short 2>/dev/null | head -1)
        if [[ -n "$ip1" ]] && [[ -n "$ip2" ]] && [[ "$ip1" != "$ip2" ]]; then
            log_result "WARN" "DNS poisoning suspected - different answers from different resolvers"
            log_result "INFO" "  1.1.1.1: $ip1"
            log_result "INFO" "  8.8.8.8: $ip2"
        fi
    fi
    
    # Check systemd-resolved status
    if command -v resolvectl &>/dev/null; then
        local dns_state=$(resolvectl status 2>/dev/null | grep -i "DNS Servers" | head -1)
        if [[ -n "$dns_state" ]]; then
            log_result "INFO" "systemd-resolved: $dns_state"
        fi
    fi
    
    if [[ "$dns_success" -ge 2 ]]; then
        return 0
    else
        return 1
    fi
}

# ============================================================
# LAYER 8: HTTPS / TLS / ACTUAL BROWSING
# ============================================================

check_https() {
    log "INFO" "=== LAYER 8: HTTPS & BROWSING ==="
    local all_pass=true
    local https_success=0
    
    # Test captive portal detection
    if command -v curl &>/dev/null; then
        local portal_response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$CAPTIVE_PORTAL_TEST" 2>/dev/null)
        if [[ "$portal_response" == "204" ]]; then
            log_result "PASS" "No captive portal detected"
        elif [[ -n "$portal_response" ]]; then
            log_result "WARN" "Captive portal detected (HTTP $portal_response)"
            all_pass=false
        fi
    fi
    
    # Test HTTPS targets
    for target in "${HTTPS_TARGETS[@]}"; do
        if command -v curl &>/dev/null; then
            local http_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout "$CURL_TIMEOUT" --max-time 10 "$target" 2>/dev/null)
            if [[ "$http_code" =~ ^[23][0-9][0-9]$ ]]; then
                log_result "PASS" "HTTPS: $target (HTTP $http_code)"
                ((https_success++))
            else
                log_result "WARN" "HTTPS: $target failed (HTTP $http_code)"
                all_pass=false
            fi
        elif command -v wget &>/dev/null; then
            if wget --spider --timeout=5 "$target" 2>/dev/null; then
                log_result "PASS" "HTTPS: $target reachable"
                ((https_success++))
            else
                log_result "WARN" "HTTPS: $target failed"
                all_pass=false
            fi
        else
            log_result "WARN" "curl/wget not installed - skipping HTTPS tests"
            all_pass=false
            break
        fi
    done
    
    # Check for MTU issues
    if [[ "$https_success" -lt 2 ]] && [[ -n "$DEFAULT_GATEWAY" ]]; then
        log_result "INFO" "Testing MTU..."
        if ping -M do -s 1472 -c 1 "$DEFAULT_GATEWAY" &>/dev/null; then
            log_result "PASS" "MTU: 1500 works"
        else
            log_result "WARN" "MTU issues detected - try reducing MTU to 1400"
            all_pass=false
        fi
    fi
    
    [[ "$all_pass" == "true" ]] && return 0 || return 1
}

# ============================================================
# LAYER 9: NETWORKMANAGER
# ============================================================

check_networkmanager() {
    log "INFO" "=== LAYER 9: NETWORKMANAGER ==="
    local all_pass=true
    
    if ! command -v nmcli &>/dev/null; then
        log_result "INFO" "NetworkManager not installed (using other network stack)"
        return 0
    fi
    
    # Check if NM is running
    if systemctl is-active NetworkManager &>/dev/null; then
        log_result "PASS" "NetworkManager is running"
    else
        log_result "FAIL" "NetworkManager is NOT running"
        return 1
    fi
    
    # Check NM state
    local nm_state=$(nmcli -t -f GENERAL.STATE general status 2>/dev/null | cut -d: -f2)
    if [[ -n "$nm_state" ]]; then
        log_result "INFO" "NetworkManager state: $nm_state"
        if [[ "$nm_state" == "connected" ]] || [[ "$nm_state" == "connecting" ]]; then
            log_result "PASS" "NetworkManager has connection"
        else
            log_result "WARN" "NetworkManager state is '$nm_state'"
            all_pass=false
        fi
    fi
    
    # Check device status
    nmcli device status 2>/dev/null | while read -r line; do
        if [[ "$line" =~ ^[^ ]+[[:space:]]+[^ ]+[[:space:]]+connected ]]; then
            log_result "PASS" "$line"
        fi
    done
    
    # Check for stale connections
    local stale_connections=$(nmcli connection show --active 2>/dev/null | grep -c " (stale)")
    if [[ "$stale_connections" -gt 0 ]]; then
        log_result "WARN" "Stale connections detected ($stale_connections)"
        all_pass=false
    fi
    
    [[ "$all_pass" == "true" ]] && return 0 || return 1
}

# ============================================================
# LAYER 10: VIRTUALIZATION (KVM/Libvirt)
# ============================================================

check_virtualization() {
    log "INFO" "=== LAYER 10: VIRTUALIZATION ==="
    
    if [[ "$HAS_LIBVIRT" != "true" ]]; then
        log_result "INFO" "No libvirt detected - skipping virtualization checks"
        return 0
    fi
    
    local all_pass=true
    
    # Check libvirtd
    if systemctl is-active libvirtd &>/dev/null; then
        log_result "PASS" "libvirtd is running"
    else
        log_result "WARN" "libvirtd is NOT running"
        all_pass=false
    fi
    
    # Check VMs
    if command -v virsh &>/dev/null; then
        local running_vms=$(virsh list --state-running --name 2>/dev/null | wc -l)
        local defined_vms=$(virsh list --all --name 2>/dev/null | wc -l)
        log_result "INFO" "VMs: $running_vms running / $defined_vms defined"
    fi
    
    [[ "$all_pass" == "true" ]] && return 0 || return 1
}

# ============================================================
# LAYER 11: KUBERNETES (Optional)
# ============================================================

check_kubernetes() {
    log "INFO" "=== LAYER 11: KUBERNETES ==="
    
    if [[ "$HAS_KUBECTL" != "true" ]]; then
        log_result "INFO" "No kubectl detected - skipping Kubernetes checks"
        return 0
    fi
    
    # Check if kubeconfig exists
    local kubeconfig="${KUBECONFIG:-$HOME/.kube/config}"
    if [[ ! -f "$kubeconfig" ]]; then
        log_result "INFO" "No kubeconfig found - skipping Kubernetes checks"
        return 0
    fi
    
    # Test cluster connectivity
    if kubectl cluster-info --request-timeout=5s &>/dev/null; then
        log_result "PASS" "Kubernetes API accessible"
        
        local nodes=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready" || echo "0")
        local total=$(kubectl get nodes --no-headers 2>/dev/null | wc -l || echo "0")
        log_result "INFO" "Kubernetes: $nodes/$total nodes ready"
    else
        log_result "WARN" "Kubernetes API not accessible"
        return 1
    fi
    
    return 0
}

# ============================================================
# REPAIR ENGINE
# ============================================================

repair_network() {
    log "INFO" "=== REPAIR ENGINE ==="
    log "INFO" "Starting targeted repairs..."
    local repaired=false
    
    # Stage 1: DNS cache flush (always safe)
    log "INFO" "Stage 1: Flushing DNS cache"
    if command -v resolvectl &>/dev/null; then
        resolvectl flush-caches 2>/dev/null && log_result "PASS" "DNS cache flushed (resolvectl)" && repaired=true
    fi
    if command -v systemd-resolve &>/dev/null; then
        systemd-resolve --flush-caches 2>/dev/null && log_result "PASS" "DNS cache flushed (systemd-resolve)" && repaired=true
    fi
    if command -v nscd &>/dev/null; then
        systemctl restart nscd 2>/dev/null && log_result "PASS" "nscd restarted" && repaired=true
    fi
    
    # Stage 2: Flush ARP cache (safe)
    log "INFO" "Stage 2: Flushing ARP cache"
    ip neigh flush all 2>/dev/null && log_result "PASS" "ARP cache flushed" && repaired=true
    
    # Stage 3: Reconnect interface (gentle)
    if command -v nmcli &>/dev/null; then
        log "INFO" "Stage 3: Reconnecting interface"
        if nmcli device status | grep -q "$DEFAULT_IFACE"; then
            nmcli device disconnect "$DEFAULT_IFACE" 2>/dev/null
            sleep 1
            nmcli device connect "$DEFAULT_IFACE" 2>/dev/null
            log_result "PASS" "Interface reconnected"
            repaired=true
            sleep 2
        fi
    fi
    
    # Stage 4: Renew DHCP (if using DHCP)
    log "INFO" "Stage 4: Renewing DHCP"
    local iface_to_renew="${BRIDGE_IFACE:-$DEFAULT_IFACE}"
    if command -v dhclient &>/dev/null; then
        dhclient -r "$iface_to_renew" 2>/dev/null
        dhclient "$iface_to_renew" 2>/dev/null && log_result "PASS" "DHCP lease renewed" && repaired=true
    fi
    
    # Stage 5: Restart NetworkManager (if needed)
    log "INFO" "Stage 5: Restarting NetworkManager"
    if systemctl restart NetworkManager 2>/dev/null; then
        log_result "PASS" "NetworkManager restarted"
        repaired=true
        sleep 3
    fi
    
    # Stage 6: Reset systemd-resolved
    log "INFO" "Stage 6: Restarting resolver"
    if systemctl restart systemd-resolved 2>/dev/null; then
        log_result "PASS" "systemd-resolved restarted"
        repaired=true
    fi
    
    # Stage 7: Bridge recovery (if applicable)
    if [[ -n "$BRIDGE_IFACE" ]]; then
        log "INFO" "Stage 7: Bridge recovery"
        if nmcli con up "$BRIDGE_IFACE" 2>/dev/null; then
            log_result "PASS" "Bridge $BRIDGE_IFACE brought up"
            repaired=true
        fi
    fi
    
    # Stage 8: DNS configuration fallback
    log "INFO" "Stage 8: Setting fallback DNS"
    if [[ ! -f /etc/resolv.conf ]] || ! grep -q "nameserver" /etc/resolv.conf; then
        echo "nameserver 1.1.1.1" | tee /etc/resolv.conf
        echo "nameserver 8.8.8.8" | tee -a /etc/resolv.conf
        log_result "PASS" "Fallback DNS configured"
        repaired=true
    fi
    
    if [[ "$repaired" == "true" ]]; then
        log_result "PASS" "Repairs completed - checking results..."
        return 0
    else
        log_result "WARN" "No repairs were performed (or all repairs failed)"
        return 1
    fi
}

# ============================================================
# REPORT GENERATION
# ============================================================

generate_report() {
    local results_file="$1"
    echo ""
    echo "=========================================="
    echo "    NETWORK RECOVERY REPORT"
    echo "=========================================="
    echo "Time: $(date)"
    echo "Host: $(hostname)"
    echo "Interface: $DEFAULT_IFACE"
    [[ -n "$BRIDGE_IFACE" ]] && echo "Bridge: $BRIDGE_IFACE"
    [[ -n "$DEFAULT_GATEWAY" ]] && echo "Gateway: $DEFAULT_GATEWAY"
    echo "------------------------------------------"
    cat "$results_file"
    echo "=========================================="
    echo "Full report saved to: $results_file"
    echo "Snapshots saved to: $SNAPSHOT_DIR"
    echo "=========================================="
}

# ============================================================
# MAIN COMMANDS
# ============================================================

cmd_diagnose() {
    log "INFO" "=== NETWORK DIAGNOSTIC STARTED ==="
    local results_file="$LOG_DIR/diagnostic-${TIMESTAMP}.log"
    
    {
        check_physical
        check_link_layer
        check_ip_layer
        check_routing
        check_gateway
        check_internet
        check_dns
        check_https
        check_networkmanager
        check_virtualization
        check_kubernetes
    } | tee -a "$results_file"
    
    generate_report "$results_file"
}

cmd_repair() {
    log "INFO" "=== NETWORK RECOVERY STARTED ==="
    
    # Take snapshot before any changes
    local snapshot_file=$(save_snapshot)
    log "INFO" "Pre-repair snapshot: $snapshot_file"
    
    # Run diagnostic
    local results_file="$LOG_DIR/recovery-${TIMESTAMP}.log"
    local diag_output=$(mktemp)
    
    {
        check_physical
        check_link_layer
        check_ip_layer
        check_routing
        check_gateway
        check_internet
        check_dns
        check_https
        check_networkmanager
        check_virtualization
        check_kubernetes
    } | tee -a "$diag_output"
    
    echo ""
    echo "=========================================="
    echo "    ATTEMPTING REPAIRS"
    echo "=========================================="
    
    if repair_network; then
        echo ""
        echo "=========================================="
        echo "    VERIFYING REPAIRS"
        echo "=========================================="
        sleep 3
        
        # Re-run key tests
        echo -e "\n=== POST-REPAIR VERIFICATION ==="
        check_internet
        check_dns
        check_https
    fi
    
    cat "$diag_output" | tee -a "$results_file"
    generate_report "$results_file"
}

cmd_snapshot() {
    local snapshot_file=$(save_snapshot)
    echo "✅ Snapshot saved to: $snapshot_file"
    echo ""
    echo "Quick summary:"
    echo "  Interface: $DEFAULT_IFACE"
    echo "  Gateway: ${DEFAULT_GATEWAY:-'None'}"
    echo "  Bridge: ${BRIDGE_IFACE:-'None'}"
    echo "  IP: $(ip -4 addr show "${BRIDGE_IFACE:-$DEFAULT_IFACE}" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1 || echo 'None')"
}

cmd_watch() {
    echo "🔍 Monitoring network health (Ctrl+C to stop)"
    echo ""
    while true; do
        clear
        echo "=== NETWORK HEALTH MONITOR ==="
        echo "Time: $(date)"
        echo ""
        
        # IP connectivity
        if ping -c 1 -W 1 8.8.8.8 &>/dev/null; then
            echo "  ✅ Internet: OK"
        else
            echo "  ❌ Internet: DOWN"
        fi
        
        # DNS
        if nslookup google.com &>/dev/null; then
            echo "  ✅ DNS: OK"
        else
            echo "  ❌ DNS: FAILED"
        fi
        
        # Gateway
        if [[ -n "$DEFAULT_GATEWAY" ]] && ping -c 1 -W 1 "$DEFAULT_GATEWAY" &>/dev/null; then
            echo "  ✅ Gateway: $DEFAULT_GATEWAY (reachable)"
        else
            echo "  ❌ Gateway: ${DEFAULT_GATEWAY:-'None'} (unreachable)"
        fi
        
        # Interface
        if ip link show "$DEFAULT_IFACE" | grep -q "UP"; then
            echo "  ✅ Interface: $DEFAULT_IFACE (UP)"
        else
            echo "  ❌ Interface: $DEFAULT_IFACE (DOWN)"
        fi
        
        echo ""
        echo "Press Ctrl+C to stop"
        sleep 2
    done
}

# ============================================================
# USAGE
# ============================================================

show_usage() {
    cat << EOF
Linux Network Recovery Engine v$VERSION

Usage:
    $SCRIPT_NAME diagnose   - Run full diagnostic (no changes)
    $SCRIPT_NAME repair     - Diagnose and attempt repairs
    $SCRIPT_NAME snapshot   - Save current network state
    $SCRIPT_NAME watch      - Monitor network health in real-time
    $SCRIPT_NAME help       - Show this help message

Examples:
    sudo network-recover diagnose
    sudo network-recover repair
    sudo network-recover snapshot

Supported Distributions:
    Debian, Ubuntu, Fedora, Arch, MX Linux, RHEL, and derivatives

Features:
    ✅ Physical layer (carrier, link state)
    ✅ IP layer (IPv4, IPv6, duplicate IP detection)
    ✅ Routing (default routes, metrics, blackholes)
    ✅ Gateway (ARP, reachability)
    ✅ Internet (multiple targets, ICMP + TCP)
    ✅ DNS (resolution, poisoning detection, multiple servers)
    ✅ HTTPS/TLS (actual browsing simulation)
    ✅ NetworkManager (state, device status, stale connections)
    ✅ Virtualization (KVM/Libvirt, bridges, vnets)
    ✅ Kubernetes (optional, cluster connectivity)
    ✅ Captive portal detection
    ✅ MTU analysis
    ✅ ARP cache management
    ✅ Pre-repair snapshots

Report Issues: https://github.com/your-repo/network-recover
EOF
}

# ============================================================
# MAIN
# ============================================================

main() {
    # Check for root privileges
    if [[ $EUID -ne 0 ]] && [[ "${1:-}" != "help" ]]; then
        echo "❌ This script must be run as root (sudo)"
        echo "   Usage: sudo $SCRIPT_NAME ${1:-diagnose}"
        exit 1
    fi
    
    case "${1:-diagnose}" in
        diagnose|diag)
            cmd_diagnose
            ;;
        repair|fix)
            cmd_repair
            ;;
        snapshot|snap)
            cmd_snapshot
            ;;
        watch|monitor)
            cmd_watch
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            echo "❌ Unknown command: ${1:-}"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# ============================================================
# RUN
# ============================================================

main "$@"