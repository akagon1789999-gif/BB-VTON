#!/usr/bin/env bash
#
# Deploy FASHN VTON v1.5 to Alibaba Cloud PAI-EAS with scale-to-zero.
#
#   ./deploy.sh                 full run: weights -> OSS, image -> ACR, service live
#   ./deploy.sh --skip-weights  weights already in OSS
#   ./deploy.sh --skip-build    image already in ACR (reuses IMAGE_TAG)
#   ./deploy.sh --dry-run       print the plan and the rendered config, change nothing
#
# Credentials come from the environment only -- never from arguments, and never
# echoed. Copy .env.deploy.example, fill it in, `set -a; . ./.env.deploy; set +a`.
#
set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --------------------------------------------------------------- settings
: "${REGION:=cn-shanghai}"
: "${SERVICE_NAME:=fashn_vton_15}"
: "${INSTANCE_TYPE:=ecs.gn7i-c8g1.2xlarge}"   # A10, 24 GB VRAM, Ampere
: "${MAX_REPLICAS:=3}"
: "${IMAGE_NAME:=fashn-vton}"
: "${FASHN_VTON_REF:=main}"
: "${URL_ALLOWLIST:=}"
# %/ trims a trailing slash, which TMPDIR carries on macOS.
: "${WEIGHTS_STAGING:=${TMPDIR:-/tmp}}"
WEIGHTS_STAGING="${WEIGHTS_STAGING%/}"
[[ "$WEIGHTS_STAGING" == *fashn-vton-weights ]] || WEIGHTS_STAGING="${WEIGHTS_STAGING}/fashn-vton-weights"
: "${OSS_WEIGHTS_PREFIX:=fashn-vton-1.5/weights}"
: "${EAS_ENDPOINT:=pai-eas.${REGION}.aliyuncs.com}"

# Which registry holds the image.
#
#   acr   Alibaba Container Registry. Push over the public endpoint from here,
#         have EAS pull over the VPC one -- faster, off the public internet,
#         and no credentials needed because it is the same account.
#   ghcr  GitHub Container Registry. Free, but public-internet: EAS needs
#         credentials, and every cold start pays an internet pull instead of
#         a VPC one. Chosen here because ACR Personal Edition requires an
#         individual-type account, and Enterprise Edition is a subscription.
: "${REGISTRY_KIND:=acr}"

: "${ACR_REGISTRY:=registry.${REGION}.aliyuncs.com}"
readonly ACR_REGISTRY_VPC="${ACR_REGISTRY/registry./registry-vpc.}"
: "${GHCR_REGISTRY:=ghcr.io}"

readonly OSS_INTERNAL_ENDPOINT="oss-${REGION}-internal.aliyuncs.com"
readonly OSS_PUBLIC_ENDPOINT="oss-${REGION}.aliyuncs.com"

SKIP_WEIGHTS=0
SKIP_BUILD=0
DRY_RUN=0

# --------------------------------------------------------------- plumbing
log()  { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

readonly WORKDIR="$(mktemp -d)"
cleanup() {
  local code=$?
  # ossutil config holds the access key, so it must not outlive the run --
  # removed on success, failure and interrupt alike.
  rm -rf -- "$WORKDIR"
  [[ $code -ne 0 ]] && warn "exited with status $code"
  return $code
}
trap cleanup EXIT
trap 'die "interrupted"' INT TERM

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    # Local IFS so "$*" joins on spaces; the global IFS is newline/tab.
    local IFS=' '
    printf '\033[2m  would run: %s\033[0m\n' "$*" >&2
  else
    "$@"
  fi
}

require_env() {
  local missing=()
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || missing+=("$name")
  done
  ((${#missing[@]} == 0)) || die "missing required environment: ${missing[*]}"
}

require_cmd() {
  for name in "$@"; do
    command -v "$name" >/dev/null 2>&1 || die "$name is not on PATH"
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-weights) SKIP_WEIGHTS=1 ;;
    --skip-build)   SKIP_BUILD=1 ;;
    --dry-run)      DRY_RUN=1 ;;
    -h|--help)      sed -n '2,12p' "$0"; exit 0 ;;
    *)              die "unknown argument: $1" ;;
  esac
  shift
done

# --------------------------------------------------------------- preflight
log "preflight"
require_cmd docker ossutil eascmd python3 git
require_env OSS_BUCKET ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET

case "$REGISTRY_KIND" in
  acr)  require_env ACR_NAMESPACE ACR_USERNAME ACR_PASSWORD ;;
  ghcr) require_env GHCR_OWNER GHCR_USERNAME GHCR_TOKEN ;;
  *)    die "REGISTRY_KIND must be 'acr' or 'ghcr', not '${REGISTRY_KIND}'" ;;
esac

docker buildx version >/dev/null 2>&1 \
  || die "docker buildx is required (it is what cross-builds linux/amd64 from macOS)"

# The tag ties the running service back to a commit. A dirty tree gets a
# -dirty suffix so an unreproducible image is at least labelled as one.
if [[ -z "${IMAGE_TAG:-}" ]]; then
  git_sha="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
  git diff --quiet 2>/dev/null || git_sha="${git_sha}-dirty"
  IMAGE_TAG="$(date -u +%Y%m%d)-${git_sha}"
fi
readonly IMAGE_TAG

# Where we push, where EAS pulls, and whether EAS needs credentials to do it.
case "$REGISTRY_KIND" in
  acr)
    IMAGE_PUSH="${ACR_REGISTRY}/${ACR_NAMESPACE}/${IMAGE_NAME}:${IMAGE_TAG}"
    IMAGE_PULL="${ACR_REGISTRY_VPC}/${ACR_NAMESPACE}/${IMAGE_NAME}:${IMAGE_TAG}"
    DOCKER_AUTH=""            # same account -- EAS pulls without credentials
    ;;
  ghcr)
    # ghcr.io rejects uppercase in the owner segment, and GitHub usernames
    # are commonly mixed case, so fold it rather than fail on push.
    ghcr_owner_lc="$(printf '%s' "$GHCR_OWNER" | tr '[:upper:]' '[:lower:]')"
    IMAGE_PUSH="${GHCR_REGISTRY}/${ghcr_owner_lc}/${IMAGE_NAME}:${IMAGE_TAG}"
    IMAGE_PULL="$IMAGE_PUSH"  # no VPC twin: EAS pulls the address we pushed to
    # base64 wraps at 76 columns on GNU coreutils; EAS wants one line.
    DOCKER_AUTH="$(printf '%s:%s' "$GHCR_USERNAME" "$GHCR_TOKEN" | base64 | tr -d '\n')"
    ;;
esac
readonly IMAGE_PUSH IMAGE_PULL DOCKER_AUTH
readonly OSS_WEIGHTS_PATH="oss://${OSS_BUCKET}/${OSS_WEIGHTS_PREFIX}/"

cat >&2 <<PLAN

  region        ${REGION}
  registry      ${REGISTRY_KIND}
  service       ${SERVICE_NAME}
  instance      ${INSTANCE_TYPE}   (0 .. ${MAX_REPLICAS} replicas, scale-to-zero)
  image push    ${IMAGE_PUSH}
  image pull    ${IMAGE_PULL}
  weights       ${OSS_WEIGHTS_PATH}
  fashn-vton    ${FASHN_VTON_REF}

PLAN

# ---------------------------------------------------------------- weights
# Staged locally, then synced to OSS. `download_weights.py` also warms the
# human-parser into the HF cache -- we deliberately ignore that copy here,
# because the Dockerfile bakes the parser into the image instead.
stage_weights() {
  log "staging weights in ${WEIGHTS_STAGING}"
  mkdir -p "$WEIGHTS_STAGING"

  if [[ -f "${WEIGHTS_STAGING}/model.safetensors" \
     && -f "${WEIGHTS_STAGING}/dwpose/yolox_l.onnx" \
     && -f "${WEIGHTS_STAGING}/dwpose/dw-ll_ucoco_384.onnx" ]]; then
    log "weights already staged, skipping download"
    return
  fi

  local repo="${WORKDIR}/fashn-vton-1.5"
  run git clone --depth 1 --branch "$FASHN_VTON_REF" \
      https://github.com/fashn-AI/fashn-vton-1.5.git "$repo" \
    || die "could not clone fashn-vton-1.5 at ref ${FASHN_VTON_REF}"

  run python3 -m venv "${WORKDIR}/venv"
  run "${WORKDIR}/venv/bin/pip" install --quiet --upgrade pip
  run "${WORKDIR}/venv/bin/pip" install --quiet huggingface_hub

  # download_weights.py fetches the VTON and DWPose weights, then finishes by
  # warming the human parser -- which imports fashn_human_parser, a module that
  # ships inside the fashn-vton package and is deliberately NOT installed in
  # this throwaway venv. That last step therefore always fails here, with
  # ModuleNotFoundError, *after* the three files we need are already on disk.
  #
  # We do not want its copy of the parser anyway: the Dockerfile bakes the
  # parser into the image so a cold replica does no Hub round-trip. So treat a
  # non-zero exit as expected and let verify_weights() below be the real gate --
  # it checks for the three files by name and dies if any is missing.
  run "${WORKDIR}/venv/bin/python" "${repo}/scripts/download_weights.py" \
      --weights-dir "$WEIGHTS_STAGING" \
    || warn "download_weights.py exited non-zero (expected at the human-parser step) -- verifying what landed"
}

verify_weights() {
  [[ $DRY_RUN -eq 1 ]] && return 0
  local f
  for f in model.safetensors dwpose/yolox_l.onnx dwpose/dw-ll_ucoco_384.onnx; do
    [[ -f "${WEIGHTS_STAGING}/${f}" ]] || die "expected weight file missing: ${f}"
  done
  log "weights verified ($(du -sh "$WEIGHTS_STAGING" | cut -f1))"
}

upload_weights() {
  log "uploading weights to ${OSS_WEIGHTS_PATH}"

  # A 600-perm config file rather than -i/-k flags: arguments are visible to
  # every other process on the host via ps.
  local cfg="${WORKDIR}/ossutil.cfg"
  ( umask 077; cat > "$cfg" <<CFG
[Credentials]
language=EN
endpoint=${OSS_PUBLIC_ENDPOINT}
accessKeyID=${ALIBABA_CLOUD_ACCESS_KEY_ID}
accessKeySecret=${ALIBABA_CLOUD_ACCESS_KEY_SECRET}
CFG
  )

  # -u syncs only what changed, so re-runs do not re-push 2 GB.
  run ossutil -c "$cfg" cp -r -u --jobs 8 --parallel 4 \
      "${WEIGHTS_STAGING}/" "$OSS_WEIGHTS_PATH"
  run ossutil -c "$cfg" ls "$OSS_WEIGHTS_PATH"
}

# ------------------------------------------------------------------ image
build_and_push() {
  local host user pass
  case "$REGISTRY_KIND" in
    acr)  host="$ACR_REGISTRY";  user="$ACR_USERNAME";  pass="$ACR_PASSWORD" ;;
    ghcr) host="$GHCR_REGISTRY"; user="$GHCR_USERNAME"; pass="$GHCR_TOKEN" ;;
  esac

  log "logging in to ${host}"
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '\033[2m  would run: docker login --password-stdin %s\033[0m\n' "$host" >&2
  else
    # --password-stdin, never a flag: argv is world readable via ps.
    printf '%s' "$pass" \
      | docker login --username "$user" --password-stdin "$host" \
      || die "${REGISTRY_KIND} login failed"
  fi

  # --platform linux/amd64 is not optional: EAS GPU nodes are x86_64, and an
  # image built natively on an Apple Silicon Mac is arm64 and will not start.
  log "building and pushing ${IMAGE_TAG} for linux/amd64"
  run docker buildx build \
      --platform linux/amd64 \
      --build-arg "FASHN_VTON_REF=${FASHN_VTON_REF}" \
      --tag "$IMAGE_PUSH" \
      --provenance=false \
      --push \
      .

  # ACR only: tag the VPC name at the same digest so eas_config can reference
  # it. On ghcr there is no second address -- EAS pulls what we just pushed.
  if [[ "$REGISTRY_KIND" == acr ]]; then
    run docker buildx imagetools create --tag "$IMAGE_PULL" "$IMAGE_PUSH"
  fi
}

# ---------------------------------------------------------------- service
render_config() {
  log "rendering eas_config.json"
  # `env` rather than a `VAR=val cmd` prefix: several of these are declared
  # readonly above, and bash refuses to shadow a readonly name in a prefix.
  env \
    IMAGE="$IMAGE_PULL" \
    SERVICE_NAME="$SERVICE_NAME" \
    INSTANCE_TYPE="$INSTANCE_TYPE" \
    MAX_REPLICAS="$MAX_REPLICAS" \
    OSS_INTERNAL_ENDPOINT="$OSS_INTERNAL_ENDPOINT" \
    OSS_WEIGHTS_PATH="$OSS_WEIGHTS_PATH" \
    URL_ALLOWLIST="$URL_ALLOWLIST" \
    DOCKER_AUTH="$DOCKER_AUTH" \
    python3 - <<'PY'
import copy, json, os, pathlib

template = pathlib.Path("eas_config.template.json").read_text()
for key in (
    "IMAGE", "SERVICE_NAME", "INSTANCE_TYPE", "MAX_REPLICAS",
    "OSS_INTERNAL_ENDPOINT", "OSS_WEIGHTS_PATH", "URL_ALLOWLIST",
    "DOCKER_AUTH",
):
    template = template.replace(f"__{key}__", os.environ[key])

config = json.loads(template)  # fails loudly on a malformed substitution
assert "__" not in json.dumps(config), "unsubstituted placeholder remains"

# On ACR the field is empty; EAS should not see a blank credential at all.
for container in config.get("containers", []):
    if not container.get("dockerAuth"):
        container.pop("dockerAuth", None)

out = pathlib.Path("eas_config.json")
out.write_text(json.dumps(config, indent=2) + "\n")
out.chmod(0o600)  # it carries a registry credential when REGISTRY_KIND=ghcr

# --dry-run prints this too, so redact rather than leaving a usable token in
# a terminal scrollback.
shown = copy.deepcopy(config)
for container in shown.get("containers", []):
    if container.get("dockerAuth"):
        container["dockerAuth"] = "<redacted>"
print(json.dumps(shown, indent=2))
PY

  # The render gates everything after it, so prove it produced a file
  # rather than trusting an exit status that has surprised us before.
  [[ -s eas_config.json ]] || die "eas_config.json was not rendered"
  python3 -c 'import json;json.load(open("eas_config.json"))' \
    || die "rendered eas_config.json is not valid JSON"
}

deploy_service() {
  log "configuring eascmd for ${EAS_ENDPOINT}"
  # Note: eascmd takes credentials as flags, so they are briefly visible in the
  # process table. On a shared build host, prefer a RAM role over long-lived
  # keys and drop these two lines.
  # Not routed through run(): that would print the key in --dry-run output.
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '\033[2m  would run: eascmd config -i <redacted> -k <redacted> -e %s\033[0m\n' \
      "$EAS_ENDPOINT" >&2
  else
    eascmd config \
        -i "$ALIBABA_CLOUD_ACCESS_KEY_ID" \
        -k "$ALIBABA_CLOUD_ACCESS_KEY_SECRET" \
        -e "$EAS_ENDPOINT" \
      || die "eascmd config failed"
  fi

  # Idempotent: create the first time, modify thereafter. `eascmd desc`
  # returning non-zero is how we tell the two cases apart.
  if [[ $DRY_RUN -eq 0 ]] && eascmd desc "$SERVICE_NAME" >/dev/null 2>&1; then
    log "service exists, updating in place"
    run eascmd modify "$SERVICE_NAME" -s eas_config.json
  else
    log "creating service"
    run eascmd create eas_config.json
  fi

  [[ $DRY_RUN -eq 1 ]] && return 0

  log "waiting for the service to report Running"
  local attempt
  for attempt in $(seq 1 60); do
    if eascmd desc "$SERVICE_NAME" 2>/dev/null | grep -qi 'Running'; then
      log "service is Running"
      eascmd desc "$SERVICE_NAME" || true
      return 0
    fi
    sleep 10
  done
  warn "service did not report Running within 10 minutes"
  warn "check: eascmd desc ${SERVICE_NAME}  /  eascmd logs ${SERVICE_NAME}"
  return 1
}

# ------------------------------------------------------------------- main
if [[ $SKIP_WEIGHTS -eq 0 ]]; then
  stage_weights
  verify_weights
  upload_weights
else
  log "skipping weights (--skip-weights)"
fi

if [[ $SKIP_BUILD -eq 0 ]]; then
  build_and_push
else
  log "skipping image build (--skip-build), reusing ${IMAGE_TAG}"
fi

render_config
deploy_service

cat >&2 <<DONE

  Deployed. First request after idle pays a full cold start -- image pull,
  2 GB of weights off OSS, then CUDA warmup. Budget 2-4 minutes and set your
  client timeout accordingly.

    eascmd desc ${SERVICE_NAME}
    eascmd logs ${SERVICE_NAME} -n 200

  Smoke test (token and endpoint come from the desc output above):

    curl -sS -X POST "https://\$EAS_HOST/api/predict/${SERVICE_NAME}/v1/tryon" \\
      -H "Authorization: \$EAS_TOKEN" \\
      -H 'Content-Type: application/json' \\
      -d '{"person_image":"https://.../model.jpg",
           "garment_image":"https://.../garment.jpg",
           "category":"tops"}' | python3 -m json.tool | head -20

DONE
