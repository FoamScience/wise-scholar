#!/usr/bin/env sh
# Install the wise-board release pinned in wise-board.version for this host into DIR (the binary, EULA.md,
# THIRD-PARTY-NOTICES.txt and notices/), replacing DIR whole.
#
# What each check proves:
#   wise-board.sha256  the archive is byte for byte the one whose digest was pinned in this repo, in the reviewed
#                      commit that bumped wise-board.version. This is what makes the download authentic.
#   SHA256SUMS         the release publishes the same digest: a cross-check that the pin and the release agree,
#                      not an authority of its own (it comes from the same server as the archive).
#   attestation        `gh attestation verify` proves the archive was built by wise-board's release workflow.
#                      WISE_BOARD_ATTEST=auto (default) runs it when gh is installed and logged in and says so
#                      when it cannot; off skips it; require fails without it.
#   --version          the binary runs here and is the pinned version.
#
# usage: scripts/fetch-wise-board.sh DIR
#   WISE_BOARD_BASE_URL  where the release assets are: https only, or file:// and http://127.0.0.1 or
#                        http://localhost mirrors for tests
#   WISE_BOARD_TARGET    the target triple, else this host's
#   WISE_BOARD_ATTEST    auto, off or require
set -eu

fail() { echo "wise-board: $*" >&2; exit 1; }
say() { echo "wise-board: $*"; }

dir=${1:?usage: $0 DIR}
case "$dir" in /*) ;; *) dir=$PWD/$dir ;; esac
root=$(cd "$(dirname "$0")/.." && pwd)
attest=${WISE_BOARD_ATTEST:-auto}
case "$attest" in auto | off | require) ;; *) fail "WISE_BOARD_ATTEST must be auto, off or require, not '$attest'" ;; esac

for tool in curl tar uname; do
    command -v "$tool" >/dev/null || fail "$tool is needed to fetch wise-board"
done
if command -v sha256sum >/dev/null; then
    sha256() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null; then
    sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
    fail "sha256sum or shasum is needed to fetch wise-board"
fi

version=$(tr -d ' \r\n' < "$root/wise-board.version")
echo "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || fail "wise-board.version holds '$version', not X.Y.Z"

base=${WISE_BOARD_BASE_URL:-https://github.com/FoamScience/wise-scholar/releases/download/wise-board-v$version}
base=${base%/}
case "$base" in
    https://*) proto='=https' ;;
    file:///*) proto='=file' ;;
    http://127.0.0.1/* | http://127.0.0.1:* | http://localhost/* | http://localhost:*) proto='=http' ;;
    *) fail "WISE_BOARD_BASE_URL must be https://, file:// or http://127.0.0.1 or localhost, not '$base'" ;;
esac
say "fetching from $base"

host=
case "$(uname -m)" in
    x86_64 | amd64) arch=x86_64 ;;
    aarch64 | arm64) arch=aarch64 ;;
    *) arch= ;;
esac
if [ -n "$arch" ]; then
    case "$(uname -s)" in
        Linux) host=$arch-unknown-linux-musl ;;
        Darwin) host=$arch-apple-darwin ;;
    esac
fi
target=${WISE_BOARD_TARGET:-$host}
[ -n "$target" ] || fail "no release for $(uname -s) $(uname -m); set WISE_BOARD_TARGET"

name=wise-board-$version-$target
archive=$name.tar.gz
bundle=wise-board-$version.sigstore.json

# one line "<64 hex>  <archive>" (or " *<archive>") for the archive in a sha256sum-format file, or nothing
digest_in() {
    awk -v f="$archive" '
        substr($0, 1, 64) ~ /^[0-9a-f]+$/ && substr($0, 65, 1) == " " && substr($0, 66, 1) ~ /[ *]/ \
            && substr($0, 67) == f { n++; d = substr($0, 1, 64) }
        END { if (n == 1) print d; else if (n > 1) print "many" }
    ' "$1"
}

pinned=$(digest_in "$root/wise-board.sha256")
[ "$pinned" != many ] || fail "wise-board.sha256 pins $archive more than once"
[ -n "$pinned" ] || fail "wise-board.sha256 pins no digest for $archive"

fetch() {
    curl -fsSL --proto "$proto" --proto-redir "$proto" --retry 3 --connect-timeout 20 --max-time 600 \
        -o "$2" "$base/$1"
}

mkdir -p "$(dirname "$dir")"
work=$(mktemp -d "$(dirname "$dir")/.wise-board.XXXXXX")
trap 'rm -rf "$work"' EXIT
cd "$work"

fetch "$archive" "$archive" || fail "could not download $base/$archive"
fetch SHA256SUMS SHA256SUMS || fail "could not download $base/SHA256SUMS"

actual=$(sha256 "$archive")
[ "$actual" = "$pinned" ] || fail "$archive has sha256 $actual, wise-board.sha256 pins $pinned"
published=$(digest_in SHA256SUMS)
[ "$published" != many ] || fail "SHA256SUMS lists $archive more than once"
[ -n "$published" ] || fail "SHA256SUMS has no line for $archive"
[ "$published" = "$pinned" ] || fail "SHA256SUMS gives $published for $archive, wise-board.sha256 pins $pinned"
say "$archive matches the pinned sha256 and SHA256SUMS"

if [ "$attest" = off ]; then
    say "provenance not verified (WISE_BOARD_ATTEST=off)"
elif ! command -v gh >/dev/null || ! gh auth status >/dev/null 2>&1; then
    [ "$attest" = auto ] || fail "WISE_BOARD_ATTEST=require, but gh is missing or not logged in"
    say "provenance not verified (gh missing or unauthenticated)"
elif ! fetch "$bundle" "$bundle"; then
    [ "$attest" = auto ] || fail "WISE_BOARD_ATTEST=require, but the release has no $bundle"
    say "provenance not verified (the release has no $bundle)"
else
    gh attestation verify "$archive" --bundle "$bundle" --owner FoamScience \
        --signer-workflow FoamScience/wise-board/.github/workflows/release.yml >/dev/null \
        || fail "$archive has no valid build provenance attestation"
    say "provenance verified: built by FoamScience/wise-board's release workflow"
fi

listing=$(tar -tvzf "$archive") || fail "$archive is not a readable tar.gz"
if echo "$listing" | grep -Eq '^[lhbcp]|^-.* link to '; then
    fail "$archive holds links or special files"
fi
tar -tzf "$archive" > members
while IFS= read -r member; do
    case "$member" in
        "$name/" | "$name/wise-board" | "$name/EULA.md" | "$name/THIRD-PARTY-NOTICES.txt" | "$name/notices/") ;;
        "$name/notices/"*/* | *..*) fail "$archive holds an unexpected member: $member" ;;
        "$name/notices/"*.txt) ;;
        *) fail "$archive holds an unexpected member: $member" ;;
    esac
done < members

mkdir unpacked
tar -xzf "$archive" -C unpacked --no-same-owner
src=unpacked/$name
[ -f "$src/wise-board" ] && [ -x "$src/wise-board" ] || fail "$archive has no wise-board binary"
[ -f "$src/EULA.md" ] || fail "$archive has no EULA.md"

if [ "$target" = "$host" ]; then
    reported=$("$src/wise-board" --version) || fail "the wise-board binary does not run here"
    [ "$reported" = "wise-board $version" ] || fail "binary reports '$reported', expected 'wise-board $version'"
else
    say "$target is not this host ($host), so its --version was not checked"
fi

mkdir stage
cp "$src/wise-board" "$src/EULA.md" stage/
[ ! -f "$src/THIRD-PARTY-NOTICES.txt" ] || cp "$src/THIRD-PARTY-NOTICES.txt" stage/
[ ! -d "$src/notices" ] || cp -R "$src/notices" stage/
printf '%s\n' "$version $target $pinned" > stage/.installed

[ ! -e "$dir" ] || mv "$dir" old
mv stage "$dir"
say "wise-board $version ($target) installed in $dir; it is proprietary and runs under $dir/EULA.md"
