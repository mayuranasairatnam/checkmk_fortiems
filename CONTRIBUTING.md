# Contributing

Changes to the Checkmk FortiClient EMS plugin should preserve tenant isolation,
valid zero measurements, secret references and explicit missing-data states.
Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Contributions use
[GPL-2.0-or-later](LICENSE). Start with the [README](README.md) and the
[development guide](docs/development.md) for source layout, data flow, test
coverage, reproducible builds and CI/release behavior.

## Local validation

```sh
python3 -m pip install 'requests>=2.31,<3'
python3 -B -m unittest discover -s tests -v
python3 -B build_mkp.py
```

Tests use mocked HTTPS and Checkmk API doubles. Before releasing, install the
MKP in a real Checkmk site and run discovery against the affected deployments
(On-Prem Dedicated/Shared or Cloud) and authentication methods. Record live
validation separately from offline test results.
Include the Checkmk/EMS versions and sanitized response fixtures in bug reports.
Never publish passwords, tokens, cookies, customer data or full server settings.

Sources live under `cmk_addons_plugins/fortiems/`. Preserve multiline module and
function docstrings, documenting purpose, inputs and outputs. Add meaningful
regression coverage for changes to transport, parsing, discovery and check behavior.
Generated MKPs, virtual environments and Python caches are excluded from Git.

CI runs tests and creates the versioned `check_fortiems` package. Describe the
resulting behavior and validation in pull requests; do not publish release tags
as part of an ordinary contribution. Identify substantial AI assistance and
review generated code before submitting it.

## Documentation changes

Keep the README concise, retaining its header and service/authentication comparison.
Put detailed setup and update steps in [installation](docs/installation.md),
credentials and API behavior in [authentication](docs/authentication.md), and
services, units, calculations and graphs in [monitoring](docs/monitoring.md).
Keep source, test and release details in [development](docs/development.md).
Each guide must link back to the README and the other three guides.

Write documentation in English and verify claims against the EMS implementation.
Preserve existing details without duplicating instructions across guides. Check
local file links and heading anchors after edits. Documentation restructuring
alone must not change plugin behavior or bump the package version.
