#!/usr/bin/env bash
# disk_monitor.sh — Periodic disk I/O monitoring with colored output
# Usage: ./disk_monitor.sh [INTERVAL_SECONDS] [DEVICE_FILTER]
# Defaults: interval=10s, all block devices

set -euo pipefail

INTERVAL="${1:-10}"
DEVICE_FILTER="${2:-}"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
util_color() {
    local val="${1%.*}"     # strip decimals
    if   (( val >= 90 )); then echo -e "${BOLD}${RED}"
    elif (( val >= 60 )); then echo -e "${YELLOW}"
    elif (( val >= 30 )); then echo -e "${CYAN}"
    else                       echo -e "${GREEN}"
    fi
}

bar() {
    local pct="${1%.*}"
    local width=20
    local filled=$(( pct * width / 100 ))
    (( filled > width )) && filled=$width
    local empty=$(( width - filled ))
    printf '%*s' "$filled" '' | tr ' ' '#'
    printf '%*s' "$empty"  '' | tr ' ' '-'
}

hr() { printf "${DIM}%s${RESET}\n" "$(printf '─%.0s' {1..72})"; }

check_deps() {
    for cmd in iostat df awk; do
        if ! command -v "$cmd" &>/dev/null; then
            echo -e "${RED}Missing dependency: $cmd${RESET}" >&2
            [[ "$cmd" == "iostat" ]] && echo "  Install: sudo apt install sysstat" >&2
            exit 1
        fi
    done
}

get_devices() {
    if [[ -n "$DEVICE_FILTER" ]]; then
        echo "$DEVICE_FILTER"
        return
    fi
    # list block devices that are actual disks (not partitions, loops, ram)
    lsblk -dno NAME 2>/dev/null | grep -Ev '^(loop|ram|zram)' || \
        ls /sys/block/ | grep -Ev '^(loop|ram|zram)'
}

disk_space() {
    # print per-device space usage from df
    df -h --output=source,size,used,avail,pcent,target 2>/dev/null \
        | grep -v tmpfs | grep -v udev | grep -v efivarfs \
        | grep -v '^/dev/loop' | grep -v '^Filesystem' | sort -k6
}

# ── Main loop ─────────────────────────────────────────────────────────────────
check_deps

IOSTAT_TMP="$(mktemp)"
trap 'echo -e "\n${CYAN}Monitoring stopped.${RESET}"; tput cnorm; rm -f "$IOSTAT_TMP"; exit 0' INT TERM
tput civis   # hide cursor

ITERATION=0

while true; do
    ITERATION=$(( ITERATION + 1 ))

    # ── Run iostat in the background, writing to a temp file ─────────────────
    iostat -xdy "$INTERVAL" 1 >"$IOSTAT_TMP" 2>/dev/null &
    IOSTAT_PID=$!

    # ── Collect disk space and queue depth while iostat runs ──────────────────
    SPACE_OUT="$(disk_space)"
    QUEUE_OUT=""
    while IFS= read -r dev; do
        stat_file="/sys/block/$dev/stat"
        [[ -f "$stat_file" ]] || continue
        read -r r_ios _ _ _ w_ios _ _ _ io_prog _ _ < "$stat_file"
        QUEUE_OUT+="$dev $r_ios $w_ios ${io_prog:-0}"$'\n'
    done < <(get_devices)

    # ── Wait for iostat to finish ──────────────────────────────────────────────
    wait "$IOSTAT_PID"
    TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

    # ── Build full output buffer ───────────────────────────────────────────────
    BUF=""
    nl=$'\n'

    # Header
    BUF+="${BOLD}${BLUE}╔══════════════════════════════════════════════════════════════════════╗${RESET}${nl}"
    BUF+="$(printf "${BOLD}${BLUE}║${RESET}  ${BOLD}💽  DISK MONITOR${RESET}   %-30s  iter: ${CYAN}%-4s${RESET} ${BOLD}${BLUE}║${RESET}" "$TIMESTAMP" "$ITERATION")${nl}"
    BUF+="${BOLD}${BLUE}╚══════════════════════════════════════════════════════════════════════╝${RESET}${nl}"
    BUF+="  Interval: ${CYAN}${INTERVAL}s${RESET}  │  Press ${BOLD}Ctrl+C${RESET} to quit${nl}${nl}"

    # I/O Utilization
    BUF+="${BOLD}${MAGENTA}▸ I/O Utilization${RESET}${nl}"
    BUF+="$(hr)${nl}"
    BUF+="$(printf "  ${BOLD}%-12s  %6s  %6s  %8s  %8s  %7s  %7s  %6s${RESET}" \
        "Device" "r/s" "w/s" "rkB/s" "wkB/s" "await" "w_await" "%util")${nl}"
    BUF+="$(hr)${nl}"

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        util="$(echo "$line" | awk '{print $NF}')"
        util_int="${util%.*}"; util_int="${util_int:-0}"
        col="$(util_color "$util_int")"
        barcol="$(bar "$util_int")"
        BUF+="$(printf "%b%s%b  [%s]" "$col" "$line" "$RESET" "$barcol")${nl}"
    done < <(awk '
        /^[a-z]/ && !/^Device/ && !/^Linux/ && !/^loop/ {
            n=NF
            printf "  %-12s  %6.1f  %6.1f  %8.1f  %8.1f  %7.2f  %7.2f  %6.1f\n",
                $1, $2, $3, $4, $5, $(n-3), $(n-2), $n
        }
    ' "$IOSTAT_TMP")

    BUF+="${nl}$(hr)${nl}"

    # Disk Space
    BUF+="${BOLD}${MAGENTA}▸ Disk Space${RESET}${nl}"
    BUF+="$(hr)${nl}"
    BUF+="$(printf "  ${BOLD}%-22s  %6s  %6s  %6s  %5s  %s${RESET}" \
        "Source" "Size" "Used" "Avail" "Use%" "Mounted on")${nl}"
    BUF+="$(hr)${nl}"

    while read -r src size used avail pct mount; do
        pct_int="${pct%%%}"; pct_int="${pct_int:-0}"
        col="$(util_color "$pct_int")"
        barcol="$(bar "$pct_int")"
        BUF+="$(printf "  %b%-22s  %6s  %6s  %6s  %4s%%  %-20s%b  [%s]" \
            "$col" "$src" "$size" "$used" "$avail" "$pct_int" "$mount" "$RESET" "$barcol")${nl}"
    done <<< "$SPACE_OUT"

    BUF+="${nl}$(hr)${nl}"

    # Queue Depth
    BUF+="${BOLD}${MAGENTA}▸ I/O Queue Depth (/sys/block/*/stat)${RESET}${nl}"
    BUF+="$(hr)${nl}"
    BUF+="$(printf "  ${BOLD}%-12s  %10s  %10s  %12s${RESET}" \
        "Device" "reads" "writes" "io_in_progress")${nl}"
    BUF+="$(hr)${nl}"

    while read -r dev r_ios w_ios io_prog; do
        [[ -z "$dev" ]] && continue
        col="${GREEN}"
        (( io_prog > 50  )) && col="${YELLOW}"
        (( io_prog > 200 )) && col="${RED}"
        BUF+="$(printf "  %b%-12s  %10s  %10s  %12s%b" \
            "$col" "$dev" "$r_ios" "$w_ios" "$io_prog" "$RESET")${nl}"
    done <<< "$QUEUE_OUT"

    BUF+="${nl}  ${DIM}Next refresh in ${INTERVAL}s…${RESET}${nl}"

    # ── Single atomic paint ───────────────────────────────────────────────────
    clear
    printf '%b' "$BUF"
done
