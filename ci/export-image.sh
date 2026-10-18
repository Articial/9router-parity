#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == Articial/9router-parity && "$(uname -m)" == x86_64 ]]
sha256sum --check SHA256SUMS >/dev/null
scratch=$(mktemp -d "${RUNNER_TEMP:?}/nine-export.XXXXXX")
source_dir="$scratch/source"
export NINE_CI_RUNTIME="$scratch/metadata"
mkdir -m 700 "$NINE_CI_RUNTIME"
git init -q "$source_dir"
git -C "$source_dir" remote add origin https://github.com/decolua/9router.git
git -C "$source_dir" fetch -q --depth=1 origin a99cf57239ff778b61e434c2786009d5ed1c412c
git -C "$source_dir" checkout -q --detach FETCH_HEAD
[[ $(git -C "$source_dir" rev-parse HEAD) == a99cf57239ff778b61e434c2786009d5ed1c412c ]]
git -C "$source_dir" apply --check "$PWD/duplicate-done.patch"
git -C "$source_dir" apply "$PWD/duplicate-done.patch"
cp package-lock.json "$source_dir/package-lock.json"
# Keep the existing Dockerfile; lock the dependency layer instead of resolving ranges again.
SOURCE_DIR="$source_dir" python3 - <<'PY'
import pathlib,os,hashlib
root=pathlib.Path(os.environ['SOURCE_DIR']);p=root/'Dockerfile';s=p.read_text()
assert s.count('COPY package.json ./')==1 and s.count('    npm install \\')==1
s=s.replace('COPY package.json ./','COPY package.json package-lock.json ./').replace('    npm install \\','    npm ci \\')
p.write_text(s)
assert hashlib.sha256((root/'open-sse/utils/stream.js').read_bytes()).hexdigest()=='9d8f7a780f078dc5d9a23486517e60a651cd2f26d3a9cdb773187c6dc4acd0fb'
PY
phase=build
docker buildx build --platform linux/amd64 --load --provenance=false \
  --metadata-file "$NINE_CI_RUNTIME/build.json" \
  --build-arg NODE_IMAGE=node:22.23.2-alpine@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85 \
  --build-arg APP_VERSION=0.5.95-donefix --tag 9router-parity:local "$source_dir"
phase=image-verification
[[ $(docker image inspect --format '{{.Os}}/{{.Architecture}}' 9router-parity:local) == linux/amd64 ]]
actual=$(docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 1000:1000 --entrypoint sha256sum 9router-parity:local /app/open-sse/utils/stream.js)
[[ "${actual%% *}" == 9d8f7a780f078dc5d9a23486517e60a651cd2f26d3a9cdb773187c6dc4acd0fb ]]

out="$RUNNER_TEMP/nine-export-output"
mkdir -m 700 "$out"
docker image inspect --format '{{.Id}}' 9router-parity:local > "$out/IMAGE_ID"
printf '%s\n' "${actual%% *}" > "$out/STREAM_SHA256"
docker save 9router-parity:local | gzip -1 > "$out/9router-linux-amd64.tar.gz"
(cd "$out" && sha256sum 9router-linux-amd64.tar.gz IMAGE_ID STREAM_SHA256 > SHA256SUMS)
# No real credentials, registry publication, provider requests or VPS access.
# This is a NEW build. Its image ID must be verified and tested on staging.
