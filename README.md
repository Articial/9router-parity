# Disposable 9router Linux parity

Manual-only, public scratch CI for 9router 0.5.95 at `a99cf57239ff778b61e434c2786009d5ed1c412c`, plus the reviewed duplicate-DONE patch. No publication or execution is authorized by the existence of these files.

The workflow uses only the standard GitHub-hosted `ubuntu-24.04` runner in the exact public repository `Articial/9router-parity`. Private repositories, larger/self-hosted runners, repeat run attempts, pushes, pull requests, deployments, image pushes, and artifact uploads are excluded. Repository Actions eligibility must be checked after approved creation and before dispatch. No repository secrets are needed or referenced.

Only the public upstream checkout forms the build context. `package-lock.json` contains public npm resolutions only. The existing upstream Dockerfile receives two build-only edits: copy the lockfile and use `npm ci` instead of `npm install`. The Node base image is digest-pinned. This fixes source and npm dependency inputs; Alpine package repositories and generated build metadata still prevent a promise of byte-identical rebuilds. Image and manifest digests identify the exact tested output; the image remains local to the ephemeral runner.

The reviewed security bootstrap, mock, fixtures, and HTTP checks are reused. Runtime containers use a Docker internal network, disposable volume, non-root users, read-only root filesystems, dropped capabilities, no-new-privileges, no extra swap, and a loopback-only router port. Synthetic secrets are generated on the runner outside the build context and never printed. Compression, request logging, cloud/tunnel integrations, and observability remain disabled. No real providers or OAuth are configured.

The bounded sequential smoke checks startup, API-key enforcement, JSON, exact SSE content/finish/one DONE, tools, and ordered 429/503 fallback. Limits are 32 router requests, 128 mock upstream attempts, and a maximum 300-second client window. Cleanup revokes the key, stops/removes test containers, deletes their volume/network and temporary files, and writes sanitized results to the job log/summary. No images or raw request logs are uploaded.

Passing this job establishes Linux/amd64 Docker behavior only. It does not establish VPS admission headroom, provider compatibility, backup recovery readiness, or permission to deploy/cut over.
