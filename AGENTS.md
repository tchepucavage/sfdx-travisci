# AGENTS.md

## Cursor Cloud specific instructions

### What this project is
This is a **Salesforce DX** sample project (see `sfdx-project.json`). The "application" is
Apex metadata under `force-app/main/default/classes/` (`myclass`, `mytest`). It ships with
CI configs (`.travis.yml`, `.circleci/config.yml`) that authenticate to a Salesforce Dev Hub,
create a scratch org, push source, and run Apex tests. There is **no local runtime / server** —
Apex only executes on a Salesforce org.

### Tooling (installed by the update script)
- **Salesforce CLI** (`sf`) — installed as a global npm package.
- **Code Analyzer** plugin (`code-analyzer`) — PMD-based static analysis for Apex (runs locally, no org).
- Java 21 is already present (required by the Code Analyzer / PMD).

### Non-obvious environment gotcha (important)
In the raw (non-login) shell used by tools, `node` may resolve to `/exec-daemon/node`, which makes
`npm config get prefix` return `/` (unwritable → global installs fail with `EACCES`). Before running
`npm`/`sf`, make sure **nvm's node is active** — either use a login shell (`bash -l`) or run
`source "$HOME/.nvm/nvm.sh"` first. With nvm active, `sf` lives on `PATH` at the nvm global bin.

### Lint / validate (work locally, no org needed)
- Lint (Apex static analysis): `sf code-analyzer run --workspace force-app --view detail`
- Validate project structure (manifest): `sf project generate manifest --source-dir force-app --name /tmp/package.xml`
- Validate by converting to metadata format: `sf project convert source --root-dir force-app --output-dir /tmp/mdout`

### Deploy & run Apex tests (requires an authenticated org — NOT available by default)
Deploying source and running Apex tests needs a Salesforce Dev Hub authenticated via JWT. This
requires secrets that are not present in this environment: the connected-app **consumer key**, a
Dev Hub **username**, and a **private key** (`assets/server.key`, currently only stored encrypted as
`server.key.enc`). Without these, `sf` cannot reach an org. Reference commands (see the CI configs):
```
sf org login jwt --client-id <CONSUMERKEY> --jwt-key-file assets/server.key --username <USERNAME> --set-default-dev-hub
sf org create scratch -f config/project-scratch-def.json -a ciorg --set-default
sf project deploy start -o ciorg
sf apex run test -o ciorg --wait 10
```
