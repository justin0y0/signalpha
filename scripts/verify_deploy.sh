#!/usr/bin/env bash
# Post-deploy verification. Run this after EVERY deploy, before saying it worked.
#
# Written after taking the site down: a backend rebuild handed the container a new
# IP, nginx had cached the old one at startup, and every API call returned 502 --
# every tab including /admin -- while the backend itself was healthy on localhost.
# The deploy checks in use at the time all passed, because they only asked "is my
# code inside the container", which is a question about me rather than about
# whether anyone can use the site.
#
# Rule: verify from OUTSIDE, through the real hostname, the way a visitor arrives.
#
#   ./scripts/verify_deploy.sh                     # checks https://signalpha.app
#   ./scripts/verify_deploy.sh http://localhost    # or a specific origin
set -uo pipefail

BASE="${1:-https://signalpha.app}"
fail=0

check() {
  local path="$1" expect="${2:-200}"
  local code
  code=$(curl -sk -m 15 -o /dev/null -w "%{http_code}" "$BASE$path" 2>/dev/null || echo "000")
  if [ "$code" = "$expect" ]; then
    printf "  \033[32mok\033[0m   %-34s %s\n" "$path" "$code"
  else
    printf "  \033[31mFAIL\033[0m %-34s %s (expected %s)\n" "$path" "$code" "$expect"
    fail=$((fail + 1))
  fi
}

echo "verifying $BASE"
echo
echo "API — these break first when nginx holds a stale upstream address"
for ep in /api/v1/health /api/v1/calendar /api/v1/performance /api/v1/brief \
          /api/v1/showdown /api/v1/track-record/summary /api/v1/pulse/track-record \
          /api/v1/oracle/signals /api/v1/simulator/dashboard /api/v1/entitlement; do
  check "$ep"
done

echo
echo "Pages"
for p in / /brief /model /strategy /pulse /oracle /about /contact /admin; do
  check "$p"
done

echo
echo "Retired paths still redirect"
for p in /performance /track-record /backtest /showdown /simulator; do
  check "$p"
done

echo
if [ "$fail" -eq 0 ]; then
  echo -e "\033[32mall checks passed\033[0m"
else
  echo -e "\033[31m$fail check(s) failed — the deploy is NOT good\033[0m"
  echo "If the API is 502 while the backend is healthy on localhost, nginx is holding"
  echo "a stale upstream IP: restart the frontend container, or confirm nginx.conf"
  echo "still resolves the backend through a variable."
fi
exit "$fail"
