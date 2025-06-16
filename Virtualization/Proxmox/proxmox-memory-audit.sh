#!/bin/bash
#
# Script d'audit mémoire pour Proxmox (VMs & LXCs)
# VERSION Ultime v2 : Ajout d'un indicateur de progression.
#

# --- Définition des couleurs ---
C_RESET=$'\033[0m'
C_GREEN=$'\033[0;32m'
C_YELLOW=$'\033[0;33m'
C_RED=$'\033[0;31m'

# --- Définition du séparateur ---
SEPARATOR=$(printf -- '-%.0s' {1..82})

# --- Initialisation ---
total_alloc=0
total_used=0
declare -a output_array=()

# --- Affichage de l'indicateur de progression ---
printf "Processing guests: "

# --- Traitement des VMs ---
while read -r id name status; do
    [ "$status" != "running" ] && continue
    printf "." # Affiche un point pour chaque VM traitée
    alloc=$(qm config "$id" | awk -F': ' '/^memory:/ {print $2}')
    [ -z "$alloc" ] && alloc=0
    pid_file="/var/run/qemu-server/${id}.pid"
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        used_kb=$(grep VmRSS "/proc/$pid/status" 2>/dev/null | awk '{print $2}')
        [ -n "$used_kb" ] && used=$((used_kb / 1024)) || used="?"
    else
        used="?"
    fi
    color=$C_RESET
    if [[ "$used" =~ ^[0-9]+$ && "$alloc" -gt 0 ]]; then
        percent=$((used * 100 / alloc))
        if [ "$percent" -lt 50 ]; then color=$C_GREEN; elif [ "$percent" -lt 85 ]; then color=$C_YELLOW; else color=$C_RED; fi
    else
        percent="?"
    fi
    output_array+=( "$(printf "%-8s %-20s %-6s %15s %15s %s%9s%%%s" "$id" "$name" "VM" "$alloc" "$used" "$color" "$percent" "$C_RESET")" )
    total_alloc=$((total_alloc + alloc))
    if [[ "$used" =~ ^[0-9]+$ ]]; then total_used=$((total_used + used)); fi
done < <(qm list | awk 'NR>1 {print $1, $2, $3}')

# --- Traitement des LXCs ---
while read -r id name status; do
    [ "$status" != "running" ] && continue
    printf "." # Affiche un point pour chaque LXC traité
    alloc=$(pct config "$id" | awk -F': ' '/^memory:/ {print $2}')
    [ -z "$alloc" ] && alloc=0
    used_kb=$(pct exec "$id" -- awk '/MemTotal/ {total=$2} /MemAvailable/ {avail=$2} END {print (total-avail)}' /proc/meminfo 2>/dev/null)
    [ -n "$used_kb" ] && used=$((used_kb / 1024)) || used="?"
    color=$C_RESET
    if [[ "$used" =~ ^[0-9]+$ && "$alloc" -gt 0 ]]; then
        percent=$((used * 100 / alloc))
        if [ "$percent" -lt 50 ]; then color=$C_GREEN; elif [ "$percent" -lt 85 ]; then color=$C_YELLOW; else color=$C_RED; fi
    else
        percent="?"
    fi
    output_array+=( "$(printf "%-8s %-20s %-6s %15s %15s %s%9s%%%s" "$id" "$name" "LXC" "$alloc" "$used" "$color" "$percent" "$C_RESET")" )
    total_alloc=$((total_alloc + alloc))
    if [[ "$used" =~ ^[0-9]+$ ]]; then total_used=$((total_used + used)); fi
done < <(pct list | awk 'NR>1 {print $1, $3, $2}')

# --- Calcul du pourcentage total pour le pied de page ---
host_total_ram=$(free -m | awk '/^Mem:/ {print $2}')
total_host_percent=0
color=$C_RESET
if [ "$host_total_ram" -gt 0 ] && [ "$total_used" -gt 0 ]; then
    total_host_percent=$((total_used * 100 / host_total_ram))
    if [ "$total_host_percent" -lt 50 ]; then color=$C_GREEN; elif [ "$total_host_percent" -lt 85 ]; then color=$C_YELLOW; else color=$C_RED; fi
fi
total_percent_str="(Host: ${total_host_percent}%)"

# --- Affichage Final ---
printf "\n\n" # Termine la ligne de progression et ajoute un espace
printf "%-8s %-20s %-6s %15s %15s %10s\n" "ID" "NAME" "TYPE" "ALLOCATED(MiB)" "USED(MiB)" "USED(%)"
printf "%s\n" "$SEPARATOR"
printf '%s\n' "${output_array[@]}" | sort -n -k1,1
printf "\n"
printf "%s\n" "$SEPARATOR"
printf "%-8s %-20s %-6s %15s %15s %s%10s%s\n" "" "TOTAL" "" "$total_alloc" "$total_used" "$color" "$total_percent_str" "$C_RESET"
