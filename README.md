# API-based Checkmk Plugin for FortiClient EMS

[<img src="docs/assets/octicons/download-16.svg" width="16" height="16" alt=""> Download MKP](https://github.com/mayuranasairatnam/checkmk_fortiems/releases/latest) · [<img src="docs/assets/octicons/book-16.svg" width="16" height="16" alt=""> Installation](#installation)

[<img src="docs/assets/octicons/bug-16.svg" width="16" height="16" alt=""> Report a Bug](https://github.com/mayuranasairatnam/checkmk_fortiems/issues/new?title=Bug%3A%20) · [<img src="docs/assets/octicons/light-bulb-16.svg" width="16" height="16" alt=""> Request a Feature](https://github.com/mayuranasairatnam/checkmk_fortiems/issues/new?title=Feature%3A%20) · [<img src="docs/assets/octicons/git-pull-request-16.svg" width="16" height="16" alt=""> Contribute](CONTRIBUTING.md)

---

Author: **Mayuran Asairatnam** · Package: **check_fortiems**

Monitor FortiClient EMS through a native Checkmk special agent; no agent is
required on EMS. On-Prem supports RADIUS or Local login in Dedicated and Shared
mode. Cloud uses a FortiCloud account email and Access Key.

## Authentication methods

| Service / function | On-Prem RADIUS (default) | On-Prem Local | Cloud Access Key |
| --- | --- | --- | --- |
| Credentials | Username and password | Username and password | Account email and Access Key |
| FortiClient EMS API | Yes | Yes | Yes |
| FortiClient EMS System Hostname | Yes | Yes | Not collected |
| FortiClient EMS System Serial Number | Yes | Yes | Yes |
| FortiClient EMS System Version | Yes | Yes | Yes |
| FortiClient EMS System Package Region | Yes | Yes | Yes |
| FortiClient EMS System Auto Upgrade | Yes | Yes | Not collected |
| FortiClient EMS Certificates | Yes | Yes | Not collected |
| FortiClient EMS License | Yes | Yes | Yes |
| FortiClient EMS Endpoints Windows | Yes | Yes | Yes |
| FortiClient EMS Endpoints macOS | Yes | Yes | Yes |
| FortiClient EMS Identity Providers | Yes | Yes | Yes |
| FortiClient EMS IDP &lt;NAME&gt; | Yes | Yes | Yes |
| FortiClient EMS Webfilter | Yes | Yes | Yes |
| FortiClient EMS Webfilter Profile &lt;NAME&gt; | Non-default profiles | Non-default profiles | Non-default profiles |
| FortiClient EMS Webfilter Import &lt;FIREWALL&gt; | When returned | When returned | When returned |
| Graphs for collected numeric metrics | Yes | Yes | Yes |
| Endpoint versions | OS summary; total-count graph | OS summary; total-count graph | OS summary; total-count graph |
| Deployment / scope | Dedicated (default) or Shared | Dedicated or Shared | Access Key's EMS instance; no sites |
| Session | Cookies and CSRF; no server logout | Cookies and CSRF; no server logout | Session ID; explicit logout |

Both On-Prem methods collect the same services. Shared adds site prefixes and
collects system identity, auto upgrade and certificates once in Global; other
services remain per site. Availability depends on API permissions and returned
fields. See [authentication](docs/authentication.md) and [monitoring](docs/monitoring.md).

## Installation

1. Download and enable the MKP under **Setup → Maintenance → Extension packages**.
2. Create the monitoring host with **Configured API integrations, no Checkmk agent**.
3. In **Setup**, search for **FortiClient EMS**, create an integration rule and restrict it to the host.
4. Enter the required credentials and review the monitoring scope and connection settings.
5. Save the rule, activate changes, run service discovery and accept the services.

See [installation](docs/installation.md) for the exact fields and defaults,
[authentication](docs/authentication.md) for account permissions, and
[monitoring](docs/monitoring.md) for services and thresholds.

## Tested environments

| Component | Tested versions |
| --- | --- |
| FortiClient EMS On-Prem — Dedicated and Shared | 7.4.7, 7.4.8 |
| FortiClient EMS Cloud | 7.4.7 |
| Checkmk | 2.4, 2.5 |

## Documentation

| Guide | Contents |
| --- | --- |
| [Installation](docs/installation.md) | Prerequisites, host setup, connection settings, CLI, discovery and updates |
| [Authentication and API access](docs/authentication.md) | Login methods, credentials, permissions, endpoints, sessions and errors |
| [Monitoring reference](docs/monitoring.md) | All services, metrics, units, thresholds, calculations, graphs and limitations |
| [Development](docs/development.md) | Source layout, data flow, offline tests, reproducible MKP builds and CI releases |

## Contributing and license

Independent community plugin. Not affiliated with or endorsed by Fortinet.

See the [Contributing Guidelines](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).
Licensed under [GPL-2.0-or-later](LICENSE). Copyright (C) 2026 Mayuran Asairatnam.
Provided without warranty; monitored EMS licenses are separate from this software license.

Icons: [GitHub Octicons](https://github.com/primer/octicons), licensed under [MIT](docs/assets/octicons/LICENSE).
