# CI and dependency maintenance

Every PR, default-branch push and explicit generated-update dispatch runs the same
required pipeline, including translation changes and Weblate authors. The shared
`ci / required` aggregate requires guard, quality, application, container and hygiene
to succeed. Missing, skipped, failed or cancelled jobs block merging. Require this
GitHub Actions status with up-to-date branches, include administrators, and prohibit
force pushes and deletion. Workflow permissions are read-only except trusted
publishers, with timeouts and concurrency limits. Actions use full version tags.

## Local checks and coverage

Use Python 3.13, uv and Node 24.20.0. Start with `uv sync --frozen --dev` and
`uv lock --check`. This repository disables default dev groups, so development
commands must include `--dev`. Local hooks and CI share the locked Ruff and djLint
versions instead of resolving independent hook versions or mutating files in CI.

Run `uv run --frozen --dev ruff check .` and `ruff format --check .` through the same
uv invocation. Run `uv run --frozen --dev djlint app/templates --check --profile=jinja`
and the corresponding `--lint` command. Both cover all 86 Jinja templates; Ruff
covers application, tests and support scripts. `prek run --all-files --hook-stage manual`
uses the existing pre-commit configuration. Its format hooks may fix local files;
CI skips duplicate language hooks and rejects tracked-file mutation.

`uv run --frozen --dev python scripts/check-types.py` enforces the existing ty
backlog exactly, including duplicate findings and source context. It fails on new
findings, checker crashes, malformed output and stale exemptions. The 140 inherited
diagnostics consist of 54 unused ignores, 41 method override issues, 19 argument
issues, 19 ORM base-class limitations and seven other findings. They remain visible
in `scripts/ty-baseline.json`; this is a regression gate, not a clean type check.
Fixing findings requires removing the corresponding baseline entries. Six isolated
unit tests exercise the gate's failure cases. The earlier non-blocking ty invocation
is removed; the unused Pyright configuration remains available for development.

Build browser assets once with `npm ci --prefix app/static` and
`npm --prefix app/static run build`. The build uses the installed Tailwind CLI;
three generated vendor assets are now ignored and rebuilt from the npm lockfile.
CI also syntax-checks the repository JavaScript with Node and compiles all translation
catalogs using `uv run --frozen --dev pybabel compile --use-fuzzy -d app/translations`.

With `FLASK_SKIP_SCHEDULER=true WIZARR_DISABLE_SCHEDULER=true`, run
`uv run --frozen --dev pytest --ignore=tests/e2e`. Migration tests exercise fresh
schemas, downgrade behavior and both recorded 2025.8/2025.9 upgrade paths. They no
longer query a changing GitHub release or skip unknown versions. Install Chromium
with `uv run --frozen --dev playwright install --with-deps --only-shell chromium`,
then run `uv run --frozen --dev pytest tests/e2e`. The nine existing invitation
browser flows exercise rendering, validation, failure handling and responsive layouts.
For local parallel checkouts, set a separate `TMPDIR` before running tests because
the inherited fixtures use fixed SQLite filenames within that directory.

`docker build -t wizarr-ci:local .` and
`bash scripts/smoke-container.sh wizarr-ci:local` test the actual production image.
The smoke uses a disposable container without external networking, applies the real
entrypoint migrations, checks SQLite tables/revision/integrity, and requests health,
onboarding and generated assets from Gunicorn. The exact `/health` route now
remains available before onboarding; a regression test keeps other routes behind
the setup redirect. The uv image is versioned; host npm
modules cannot overwrite Alpine dependencies. CI caches Docker layers and dependency
packages, and uploads browser failure artifacts.

## Renovate, writers and limits

The shared default/mixed presets cover Python/uv, npm, containers, actions and hooks.
Type checker changes require dashboard approval. Python and container automerge
remain disabled while the type backlog and live media-client coverage gaps remain.
Other automerge activation waits for the corrected shared policy and required checks.
Renovate updates full action/workflow versions; shared releases stay immutable.

Timestamp-only gettext extraction preserves the existing catalog files instead
of generating daily empty updates; an isolated real-extraction regression test
checks idempotency and changed messages. The nightly translation writer opens one `fix/refresh-translations` PR with DCO
signoff and explicitly dispatches full CI for that exact commit. Enable Actions PR
creation and ensure external Weblate writes through PRs before enforcing protection.
Existing upstream CalVer, release, sponsor-manifest and image publishers are guarded
to `wizarrrr/wizarr`; Blacksmith-specific builders are replaced with standard Docker
actions. The redundant disabled release workflow is removed; the inactive Plus
workflow remains inactive.

The browser tests use fixture media servers and include expected connection-failure
paths; they do not prove successful live Plex/Jellyfin/Emby or companion service
integration. Proprietary Plus code, live Weblate/publishing credentials, non-Linux
platforms and ARM container execution are not covered. There is no JavaScript type
checker or browser coverage threshold. Full Python/container automerge needs stronger
type and integration coverage before activation.
