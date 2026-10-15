#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ "${GITHUB_ACTIONS:-}" == true && "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]]
[[ "${GITHUB_REPOSITORY:-}" == Articial/9router-parity ]]
sha256sum --check SHA256SUMS >/dev/null
scratch=$(mktemp -d "${RUNNER_TEMP:?}/nine-parity.XXXXXX")
source_dir="$scratch/source"
export NINE_CI_RUNTIME="$scratch/runtime"
mkdir -m 700 "$NINE_CI_RUNTIME"
compose=(docker compose --project-directory "$PWD/ci" -f ci/compose.json)
phase=initialization
cleanup() {
  rc=$?
  trap - EXIT
  set +e
  sudo env NINE_CI_RUNTIME="$NINE_CI_RUNTIME" PARITY_PHASE="$phase" PARITY_EXIT="$rc" python3 - <<'PY'
import json,os,pathlib,subprocess
runtime=pathlib.Path(os.environ['NINE_CI_RUNTIME']);result={'phase':os.environ['PARITY_PHASE'],'exitCode':int(os.environ['PARITY_EXIT'])}
if (runtime/'client-result.json').exists():result.update(json.loads((runtime/'client-result.json').read_text()))
if (runtime/'identity.json').exists():result['image']=json.loads((runtime/'identity.json').read_text())
peaks={}
for name in ['9router-parity-router','9router-parity-mock']:
 p=subprocess.run(['docker','inspect',name],capture_output=True,text=True)
 if p.returncode:continue
 c=json.loads(p.stdout)[0];pid=c['State']['Pid']
 if pid:
  rel=next(l.split(':',2)[2] for l in pathlib.Path('/proc',str(pid),'cgroup').read_text().splitlines() if l.startswith('0::'))
  peak=pathlib.Path('/sys/fs/cgroup'+rel)/'memory.peak'
  if peak.exists():peaks[name]=int(peak.read_text())
 result.setdefault('containerState',{})[name]={'oomKilled':c['State']['OOMKilled'],'restartCount':c['RestartCount']}
result['containerMemoryPeakBytes']=peaks
(runtime/'summary.json').write_text(json.dumps(result))
PY
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1
  cleanup_rc=$?
  sudo env NINE_CI_RUNTIME="$NINE_CI_RUNTIME" CLEANUP_EXIT="$cleanup_rc" python3 - <<'PY'
import json,os,pathlib,subprocess
r=pathlib.Path(os.environ['NINE_CI_RUNTIME']);j=json.loads((r/'summary.json').read_text())
checks=[['docker','container','inspect',n] for n in ['9router-parity-router','9router-parity-mock']]+[['docker','network','inspect','9router-parity-net'],['docker','volume','inspect','9router-parity-data']]
j['cleanupPass']=int(os.environ['CLEANUP_EXIT'])==0 and all(subprocess.run(a,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0 for a in checks)
j['pass']=j.get('pass',False) and j['cleanupPass'] and not any(x['oomKilled'] or x['restartCount'] for x in j.get('containerState',{}).values())
j['vpsCapacityProven']=False
(r/'summary.json').write_text(json.dumps(j,indent=2)+'\n')
print(json.dumps(j))
raise SystemExit(0 if j['pass'] else 1)
PY
  verification_rc=$?
  [[ "$verification_rc" == 0 ]] || rc=1
  if [[ -f "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf '```json\n' >> "$GITHUB_STEP_SUMMARY"
    sudo cat "$NINE_CI_RUNTIME/summary.json" >> "$GITHUB_STEP_SUMMARY"
    printf '```\n' >> "$GITHUB_STEP_SUMMARY"
  fi
  sudo rm -rf -- "$scratch"
  [[ "$cleanup_rc" == 0 ]] || rc=1
  exit "$rc"
}
trap cleanup EXIT
phase=source
[[ $(docker info --format '{{.CgroupVersion}}') == 2 ]]
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
sudo env NINE_CI_RUNTIME="$NINE_CI_RUNTIME" python3 - <<'PY'
import pathlib,os,json,subprocess,secrets
r=pathlib.Path(os.environ['NINE_CI_RUNTIME'])
for name in ['dashboard-password','jwt-secret']:
 p=r/name;p.write_text(secrets.token_hex(32)+'\n');p.chmod(0o400);os.chown(p,1000,1000)
metadata=json.loads((r/'build.json').read_text())
assert isinstance(metadata.get('containerimage.digest'),str) and metadata['containerimage.digest'].startswith('sha256:')
image=json.loads(subprocess.check_output(['docker','image','inspect','9router-parity:local']))[0]
(r/'identity.json').write_text(json.dumps({'imageID':image['Id'],'manifestDigest':metadata.get('containerimage.digest'),'platform':image['Os']+'/'+image['Architecture'],'testedPatchSHA256':'9d8f7a780f078dc5d9a23486517e60a651cd2f26d3a9cdb773187c6dc4acd0fb','sourceCommit':'a99cf57239ff778b61e434c2786009d5ed1c412c'}))
PY
phase=startup
"${compose[@]}" config --quiet
"${compose[@]}" up -d --no-build --pull never
ready=false
for ((n=0;n<60;n++)); do
  state=$(docker inspect --format '{{.State.Health.Status}}' 9router-parity-router)
  if [[ "$state" == healthy ]]; then ready=true; break; fi
  [[ $(docker inspect --format '{{.State.Running}}' 9router-parity-router) == true ]] || break
  sleep 2
done
[[ "$ready" == true ]]
phase=http-smoke
sudo env NINE_CI_RUNTIME="$NINE_CI_RUNTIME" timeout --signal=TERM --kill-after=10s 300s python3 ci/http-smoke.py
phase=complete
