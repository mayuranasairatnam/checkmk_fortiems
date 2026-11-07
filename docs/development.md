# Development, tests and releases

[← README](../README.md) · [Installation](installation.md) · [Authentication](authentication.md) · [Monitoring](monitoring.md) · [Development](development.md)

## Source layout, tests and reproducible package build

The native special agent uses Agent-based API v2, Rulesets API v1,
Server-side Calls API v1 and Graphing API v1.

Sources live under `cmk_addons_plugins/fortiems/`. `cmk_addons/plugins` is a
symlink to `../cmk_addons_plugins`, enabling local imports through
`cmk_addons.plugins.fortiems`. Only the FortiEMS plugin sources are packaged;
the local import symlink is excluded.

| File | Purpose |
| --- | --- |
| `libexec/agent_fortiems` | On-Prem and Cloud transports, login/logout, tenant collection and JSON output |
| `server_side_calls/fortiems.py` | Builds the special-agent command with host settings and secret references |
| `rulesets/special_agent.py` | Authentication method, credentials, deployment type, login site, Shared selection and TLS settings |
| `rulesets/check_parameters.py` | Configurable thresholds and monitoring states |
| `graphing/fortiems.py` | Metrics and historical graphs |
| `agent_based/fortiems.py` | Compatibility imports for checks created before the module split |
| `agent_based/fortiems_api.py` | Shared JSON parser and global/tenant API status |
| `agent_based/fortiems_system.py` | System identity, firmware and auto-upgrade status |
| `agent_based/fortiems_license.py` | License capacity, usage and remaining lifetime |
| `agent_based/fortiems_certificates.py` | Assigned certificates and earliest expiry |
| `agent_based/fortiems_endpoints.py` | OS total metrics and version counts in OS service summaries |
| `agent_based/fortiems_idp.py` | Provider inventory, IDP availability, connector and synchronization health |
| `agent_based/fortiems_webfilter.py` | Webfilter inventory, profile settings and imported-firewall synchronization |
| `lib/common.py` | Shared validation, dates, tenant identities and discovery/check helpers |

All checks consume the shared `fortiems` agent section. Feature modules own their
plugin registrations. Compatibility attributes are resolved on demand to avoid
duplicate registration. The modules share the same ruleset IDs and metric
names; System information uses the separate field services in the
[monitoring reference](monitoring.md#monitoring-scope-and-services). Modules
and functions use multiline documentation with inputs and
outputs.

The data flow is: the Setup rule supplies connection settings, the server-side
call starts the collector, and the collector authenticates, queries the selected
sites and emits JSON. The parser validates the section; feature checks discover
services and produce states and metrics. System profile audits remain outside the
collection scope. Webfilter URL/category contents and firewall credentials are
not exported; only their counts and monitoring settings are retained.

From the project directory:

```sh
python3 -m pip install 'requests>=2.31,<3'
python3 -B -m unittest discover -s tests -v
python3 -B build_mkp.py --version 1.0.1
```

Offline tests cover Local/RADIUS and Cloud login, Cloud logout and secret handling,
authentication selection and migration,
cookie/CSRF handling, tenant isolation,
selected sites, partial failures, valid zeros, missing/invalid measurements,
license calculations, expiry, configurable states, dynamic services, rule and
graph definitions, unique registration and deterministic package contents.
They make no appliance connections. API doubles do not replace installation,
discovery and monitoring checks in a real Checkmk site. The maintainer has
confirmed operation with FortiClient EMS 7.4.8.

Package construction uses the Python standard library and excludes tests,
requirements notes and Python caches. It sorts source paths, fixes archive
metadata and uses gzip timestamp zero. Identical sources and the same version
produce identical MKP bytes. To verify locally:

```sh
python3 -B build_mkp.py --version 1.0.1
cp check_fortiems-1.0.1.mkp /tmp/check_fortiems-first.mkp
python3 -B build_mkp.py --version 1.0.1
cmp /tmp/check_fortiems-first.mkp check_fortiems-1.0.1.mkp
```

The build metadata declares Checkmk 2.4.0 as the minimum required version; this
is a compatibility declaration, not evidence of live validation on Checkmk 2.4.
See [Tested environments](../README.md#tested-environments) for reported live tests.

## CI and releases

GitHub Actions runs the offline tests and builds the MKP for pull requests and
pushes to `main`. After successful tests on `main`, the release workflow creates
a Git tag and GitHub Release with the matching MKP attached. The initial release
version is `v1.0.0`; subsequent releases increment the highest stable tag's patch
version. Re-running a released commit reuses its version. Unrelated tags and
prerelease tags are ignored. Release versions are selected by `.github/scripts/release_version.py`.

The release job uses the automatic `GITHUB_TOKEN` with `contents: write`.
Installable packages are published through the repository's
[GitHub Releases](https://github.com/mayuranasairatnam/checkmk_fortiems/releases).

Local builds default to `1.0.1`. To build a specific package version:

```sh
python3 -B build_mkp.py --version 1.0.1
```

Generated MKPs are excluded from Git. Release notes are generated by GitHub.

## References

- [Checkmk special agents](https://docs.checkmk.com/latest/en/devel_special_agents.html)
- [Agent-based API v2](https://docs.checkmk.com/plugin-api/latest/cmk.agent_based/v2.html)
- [Server-side Calls API](https://docs.checkmk.com/plugin-api/latest/cmk.server_side_calls/)
- [Rulesets API](https://docs.checkmk.com/plugin-api/latest/cmk.rulesets/v1.form_specs.html)
- [Graphing API v1](https://docs.checkmk.com/plugin-api/latest/cmk.graphing/v1.graphs.html)

## Lint checks

The CI workflow defines Ruff and yamllint versions and rules directly in
`.github/workflows/ci.yml`. To repeat these checks locally, install the
listed tools and run the commands from the corresponding workflow steps.
Ruff includes extensionless `libexec/agent_*` scripts.
