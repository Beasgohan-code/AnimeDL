#!/usr/bin/env bash
# ============================================================================
#  unrar → unrar-free compatibility shim (Docker image, Debian trixie+)
# ============================================================================
#  Debian moved the non-free `unrar` package out of the default repositories
#  (trixie+). AnimeDL's extractor calls `unrar x …` with classic flags, so
#  this shim translates them onto the free `unrar-free` implementation.
#
#  Flag handling:
#    -kb -idq -idc -idp -y -ai -o+ -o- -c- -c+   → dropped (harmless no-ops)
#    -pPASSWORD                                  → passed through unchanged
#
#  If unrar-free rejects the password flag syntax, the shim retries once
#  without it so unencrypted archives still extract.
# ============================================================================
set -u

cmd="$1"
shift

rest=()
for a in "$@"; do
    case "$a" in
        -kb|-idq|-idc|-idp|-idn|-id|-y|-ai|-o+|-o-|-c-|-c+) ;;
        *) rest+=("$a") ;;
    esac
done

if unrar-free "$cmd" ${rest[@]+"${rest[@]}"}; then
    exit 0
fi

# Retry without password flags (covers -p syntax mismatches on unencrypted rar)
nop=()
dropped=0
for a in ${rest[@]+"${rest[@]}"}; do
    case "$a" in
        -p*) dropped=1 ;;
        *) nop+=("$a") ;;
    esac
done
if [ "$dropped" -eq 1 ]; then
    exec unrar-free "$cmd" ${nop[@]+"${nop[@]}"}
fi

exit 1
