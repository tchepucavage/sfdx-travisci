# AGENTS.md

## Cursor Cloud specific instructions

This repo is the **Salesforce DX (SFDX)** "Travis CI" sample. The "application" is
Apex code under `force-app/` that is deployed to and executed inside a Salesforce
org. There is **no local web app or server** to start — work happens through the
Salesforce CLI (`sf`).

### Tooling
- Node and Java come pre-installed on the VM; the update script installs the
  Salesforce CLI (`@salesforce/cli`, providing the `sf` command).
- The **Code Analyzer** (`code-analyzer`) is a JIT plugin: `sf` auto-installs it
  from npm on first use, so the first lint run needs network access.
- npm's default global prefix resolves to `/` on this VM (the primary `node` is the
  sandbox node at `/exec-daemon/node`). Install global npm packages with an explicit
  prefix derived from the nvm npm, e.g.
  `npm install --prefix "$(dirname "$(dirname "$(command -v npm)")")" --global <pkg>`.
  This lands binaries in the nvm bin dir, which is already on `PATH`.

### Build / Lint (no org required)
- Build/validate (source -> Metadata API format):
  `sf project convert source --root-dir force-app --output-dir /tmp/mdout`
- Lint (PMD via Code Analyzer):
  `sf code-analyzer run --workspace force-app --view detail`

### Run / Test (requires a Salesforce Dev Hub — NOT available by default)
Apex only runs server-side, so running the app and the Apex tests requires
authenticating to a Salesforce Dev Hub and creating a scratch org. The CI flow
(`.travis.yml`, `.circleci/config.yml`) does:
1. `sf org login jwt ...` (or `sf org login web`) to authenticate a Dev Hub.
2. `sf org create scratch -f config/project-scratch-def.json -a ciorg --set-default`
3. `sf project deploy start -o ciorg` (push source)
4. `sf apex run test -o ciorg --wait 10` (run `mytest.myUnitTest`)
5. `sf org delete scratch -o ciorg -p`

There are **no Salesforce credentials in this environment** (`sf org list` shows
none). The above run/test steps are blocked until a Dev Hub is authenticated
(JWT secrets, or an interactive `sf org login web`). Without an authenticated org,
local validation is limited to the build/lint commands above.
