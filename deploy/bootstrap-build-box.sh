#!/usr/bin/env bash
#
# Prepare a fresh Ubuntu 22.04 ECS instance to run deploy/pai-eas/deploy.sh.
#
#   curl -fsSL <this file> -o bootstrap-build-box.sh   # or scp it over
#   bash bootstrap-build-box.sh
#
# Installs docker (with buildx), ossutil, eascmd, git and python3-venv, under
# the exact command names deploy.sh's preflight looks for. Idempotent: safe to
# re-run after a failure, and it will not reinstall what is already good.
#
# It deliberately does NOT touch credentials. .env.deploy is yours to write
# afterwards; see the closing instructions.
#
# The build box is disposable. It exists because macOS 12.7.6 cannot run a
# current Docker Desktop, and because pushing ~2 GB of weights and a multi-GB
# CUDA image from a laptop in Lagos to Singapore is an afternoon you do not
# need to spend. Delete the instance once the service is live.
#
set -Eeuo pipefail
IFS=$'\n\t'

# Pinned rather than "latest": ossutil 2.x reorganised the flags that deploy.sh
# passes (-c, --jobs, --parallel), so 1.7.x is the compatible line.
readonly OSSUTIL_VERSION=1.7.18
readonly OSSUTIL_URL="https://gosspublic.alicdn.com/ossutil/${OSSUTIL_VERSION}/ossutil64"
readonly EASCMD_URL="https://eas-data.oss-cn-shanghai.aliyuncs.com/tools/eascmd/v2/eascmd64"

# Weights staging + docker layers for a CUDA image. Well under a 100 GB disk,
# but a default 40 GB one will fail partway through the build.
readonly MIN_FREE_GB=60

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

readonly WORKDIR="$(mktemp -d)"
trap 'rm -rf -- "$WORKDIR"' EXIT

# ------------------------------------------------------------------ preflight
log "preflight"

[[ "$(uname -s)" == "Linux" ]] || die "this script is for the Ubuntu build box, not your Mac"
[[ "$(uname -m)" == "x86_64" ]] \
  || die "expected x86_64; EAS GPU nodes are amd64 and the image must match"

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || warn "tested on Ubuntu; ${PRETTY_NAME:-this} may differ"
else
  warn "no /etc/os-release; assuming Debian-family"
  VERSION_CODENAME=jammy
fi

if [[ $EUID -eq 0 ]]; then
  SUDO=""
  warn "running as root; deploy.sh is happier as a normal user in the docker group"
else
  command -v sudo >/dev/null 2>&1 || die "sudo is required when not running as root"
  SUDO="sudo"
  $SUDO -v || die "sudo authentication failed"
fi
readonly SUDO

free_gb="$(df -BG --output=avail / | tail -1 | tr -dc '0-9')"
if (( free_gb < MIN_FREE_GB )); then
  die "only ${free_gb} GB free on /; the CUDA image build needs ~${MIN_FREE_GB} GB.
       Resize the system disk before continuing -- running out mid-build wastes
       the whole image pull."
fi
log "disk: ${free_gb} GB free"

# Fetch to a temp path, prove it is an executable, only then install it. A 404
# from a CDN arrives as a 200-looking HTML page often enough to be worth this.
install_binary() {
  local url="$1" dest="$2" name="$3"
  # Separate statement: bash declares every name in a `local` before running
  # its assignments, so ${name} here would be declared-but-unset and set -u
  # would abort.
  local tmp="${WORKDIR}/${name}"

  log "installing ${name}"
  curl -fsSL --retry 3 --retry-delay 2 -o "$tmp" "$url" \
    || die "could not download ${name} from ${url}"

  # ELF magic: 0x7F 'E' 'L' 'F'. An HTML error page fails here instead of
  # installing a file that only reveals itself as garbage during the deploy.
  head -c 4 "$tmp" | grep -qa $'\x7fELF' \
    || die "${name} download is not an ELF binary -- the URL may have moved.
       Check the vendor docs and update the URL at the top of this script."

  chmod +x "$tmp"
  $SUDO install -m 0755 "$tmp" "$dest"
}

# -------------------------------------------------------------------- packages
log "apt: base packages"
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq \
    ca-certificates curl gnupg git python3 python3-venv python3-pip rsync

# ---------------------------------------------------------------------- docker
# Ubuntu's own docker.io package does not ship buildx, and deploy.sh needs it
# to cross-build linux/amd64 reproducibly. So: Docker's official repo.
if docker buildx version >/dev/null 2>&1; then
  log "docker with buildx already present, skipping"
else
  log "installing docker-ce + buildx from download.docker.com"

  $SUDO install -m 0755 -d /etc/apt/keyrings
  if [[ ! -s /etc/apt/keyrings/docker.gpg ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
  fi

  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME:-jammy} stable" \
    | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null

  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq \
      docker-ce docker-ce-cli containerd.io docker-buildx-plugin

  $SUDO systemctl enable --now docker
fi

# Group membership takes effect on the next login, not this shell -- the
# closing notes say so rather than pretending otherwise.
NEEDS_RELOGIN=0
if [[ $EUID -ne 0 ]] && ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  log "adding ${USER} to the docker group"
  $SUDO usermod -aG docker "$USER"
  NEEDS_RELOGIN=1
fi

# --------------------------------------------------------------------- vendors
# deploy.sh's preflight is `require_cmd docker ossutil eascmd python3 git`, so
# these install under those bare names, not ossutil64/eascmd64.
if command -v ossutil >/dev/null 2>&1; then
  log "ossutil already present, skipping"
else
  install_binary "$OSSUTIL_URL" /usr/local/bin/ossutil ossutil
fi

if command -v eascmd >/dev/null 2>&1; then
  log "eascmd already present, skipping"
else
  install_binary "$EASCMD_URL" /usr/local/bin/eascmd eascmd
fi

# ---------------------------------------------------------------- verification
log "verifying"

failed=0
check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf '  \033[32mok\033[0m    %s\n' "$name" >&2
  else
    printf '  \033[31mFAIL\033[0m  %s\n' "$name" >&2
    failed=1
  fi
}

check "git"            git --version
check "python3"        python3 --version
check "python3 venv"   python3 -c 'import venv'
# These two vendor CLIs disagree about --version/--help and their exit codes,
# so assert only that the binary exists and executes: 127 is "not found", 126
# is "found but not executable", and anything else means it ran.
check_runs() {
  local name="$1"; shift
  local code=0
  "$@" >/dev/null 2>&1 || code=$?
  if (( code == 127 || code == 126 )); then
    printf '  \033[31mFAIL\033[0m  %s (exit %d)\n' "$name" "$code" >&2
    failed=1
  else
    printf '  \033[32mok\033[0m    %s\n' "$name" >&2
  fi
}

check_runs "ossutil"   ossutil help
check_runs "eascmd"    eascmd help
check "docker binary"  docker --version
check "docker buildx"  docker buildx version

# Distinguish "daemon is down" from "you are not in the docker group yet",
# because the fix is different and the error message is not.
if $SUDO docker info >/dev/null 2>&1; then
  printf '  \033[32mok\033[0m    docker daemon\n' >&2
else
  printf '  \033[31mFAIL\033[0m  docker daemon (try: sudo systemctl status docker)\n' >&2
  failed=1
fi

(( failed == 0 )) || die "one or more checks failed; fix those before deploying"

# --------------------------------------------------------------------- closing
cat >&2 <<NEXT

  Build box ready.

NEXT

if (( NEEDS_RELOGIN )); then
  cat >&2 <<'RELOGIN'
  FIRST: log out and back in (or run `newgrp docker`). The docker group only
  applies to new sessions -- without it every docker command needs sudo, and
  deploy.sh does not use sudo.

RELOGIN
fi

cat >&2 <<'NEXT'
  1. Get the repo onto this box -- either

       git clone <your remote> bb-vton

     or, from the Mac:

       rsync -av --exclude node_modules --exclude .git \
         "~/Documents/AI/BB Virtual try-on development/" \
         <user>@<ecs-ip>:~/bb-vton/

  2. Write the credentials file (it is gitignored, and was never on the Mac):

       cd bb-vton/deploy/pai-eas
       cp .env.deploy.example .env.deploy
       chmod 600 .env.deploy
       nano .env.deploy

     Six required values, plus REGION:

       ALIBABA_CLOUD_ACCESS_KEY_ID / _SECRET   the fashn-eas-deploy RAM user
       REGISTRY_KIND=ghcr
       GHCR_OWNER / GHCR_USERNAME / GHCR_TOKEN  classic PAT, write:packages
       OSS_BUCKET=bb-fashn-vton-weights
       REGION=ap-southeast-1                   <- uncomment this one

  3. Confirm a GPU SKU is actually available to you before uploading 2 GB:

       set -a; . ./.env.deploy; set +a
       eascmd config -i "$ALIBABA_CLOUD_ACCESS_KEY_ID" \
                     -k "$ALIBABA_CLOUD_ACCESS_KEY_SECRET" \
                     -e pai-eas.ap-southeast-1.aliyuncs.com
       eascmd instances

     Want >=8 GB VRAM, Ampere or newer. If gn7i is absent, set INSTANCE_TYPE
     in .env.deploy to one that is listed.

  4. Dry run, then the real thing:

       ./deploy.sh --dry-run
       ./deploy.sh

     --skip-weights and --skip-build let you resume without redoing the slow
     parts if something fails partway.

  5. When the service is Running: delete this ECS instance. It has served its
     purpose and it bills by the hour.

NEXT
