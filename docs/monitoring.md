# Services, metrics and thresholds

[← README](../README.md) · [Installation](installation.md) · [Authentication](authentication.md) · [Monitoring](monitoring.md) · [Development](development.md)

## Deployment and feature support

Select **On-Prem Dedicated**, **On-Prem Shared** or **Cloud** in the
**FortiClient EMS** rule. The tables describe the features implemented by this
plugin. API permissions and the fields returned by the EMS instance still
determine whether an individual check can report a measurement.

| Configuration | On-Prem Dedicated | On-Prem Shared | Cloud |
| --- | --- | --- | --- |
| Authentication | Local or RADIUS login | Local or RADIUS login | FortiCloud account email and Access Key |
| Destination | Checkmk host address and configured HTTPS port | Checkmk host address and configured HTTPS port | Fixed `forticlient.forticloud.com` gateway |
| Scope | One configured site; `default` initially | All discovered sites or selected sites, always plus Global | EMS instance associated with the Access Key |
| Site selection | Exact lowercase login site | Exact lowercase site list; empty means all, including `default` | No site or tenant selection |
| Site discovery and switching | No | Yes, sequentially | No |
| Service naming | `FortiClient EMS …` | `FortiClient EMS ["site"] …` and `["global"] …` | `FortiClient EMS …` |
| Session | Cookies and CSRF token | Cookies and CSRF token | Session ID from Access Key login; explicit logout |

| Monitoring feature | On-Prem Dedicated | On-Prem Shared | Cloud |
| --- | --- | --- | --- |
| API collection health | Yes | Host, Global and each selected site | Yes |
| System Hostname | Yes | Global only | Not collected |
| System Serial Number | Yes | Global only | Yes |
| System Version (EMS server) | Yes | Global only | Yes, from constants; confirmed live |
| System Auto Upgrade | Yes | Global only | Not collected |
| System Package Region | Yes | Per site | Yes |
| Assigned certificates and expiry | Yes | Global only | Not collected; certificate scan disabled |
| EPP / ZTNA / SASE seats, utilization and expiry | Site capacity from `vdom_seats` | Per-site capacity from `vdom_seats` | Instance capacity from `seats` |
| Assigned and used seat graphs | Yes | Per site | Yes |
| Windows and macOS endpoint totals | Yes | Per site | Yes |
| Installed FortiClient versions in summaries; OS total graphs | Yes | Per site | Yes |
| Identity provider inventory, status and synchronization | Yes | Per site | Yes |
| Webfilter inventory and custom profile checks | Yes | Per site | Yes |
| Imported firewall / webfilter synchronization | When returned by the API | Per site, when returned by the API | When returned by the API |

Cloud does not discover Hostname, Auto Upgrade or Certificates services. Cloud responses do not expose the system
fields used by these checks, and the certificate endpoint returned HTTP 404.
Cloud reads the **EMS server version** from `System.VERSION_FULL` in the
constants response, falling back to `System.VERSION`. Installed **FortiClient
endpoint versions** and their counts appear in the Windows or macOS endpoint service summary. Only the total endpoint count is graphed.

For On-Prem Shared, hostname, serial number, EMS version, auto upgrade and
certificates are collected once in the Global context. Package region,
licenses, endpoints, identity providers and webfilter remain scoped to each
selected site. All services stay on the configured EMS host; the plugin does
not create customer hosts.

## Monitoring scope and services

The following table lists the service names and metrics. Availability and scope
follow the deployment support table above. Missing or invalid measurements in
supported checks report UNKNOWN; unsupported Cloud services are not discovered.

| Service | Data / performance metrics |
| --- | --- |
| FortiClient EMS API | Connection, authentication, tenant discovery and query errors |
| FortiClient EMS System Hostname | Hostname as a separate text service |
| FortiClient EMS System Serial Number | Serial number as a separate text service |
| FortiClient EMS System Version | EMS version as a separate text service |
| FortiClient EMS System Package Region | Cloud Region to Repackage Installers from `settings.data.fct_repackager_upload_region`, for example `North America` |
| FortiClient EMS System Auto Upgrade | Configurable enabled/disabled state; `ems_auto_upgrade_enabled` (1/0) |
| FortiClient EMS License | Active EPP, ZTNA or SASE product, used/max seats, utilization, expiry and remaining days; `ems_license_used`, `ems_license_max`, `ems_license_utilization`, `ems_remaining_days` |
| FortiClient EMS Certificates | Assigned certificates, earliest expiry and remaining days; `ems_remaining_days` |
| FortiClient EMS Endpoints Windows | Total Windows endpoints and version distribution; `ems_endpoints`; counts per version in the service summary |
| FortiClient EMS Endpoints macOS | Total macOS endpoints and version distribution; `ems_endpoints`; counts per version in the service summary |
| FortiClient EMS IDP &lt;NAME&gt; | Domain, provider GUID, online/connector status and synchronization health; `ems_idp_devices`, `ems_idp_users`, `ems_sync_progress`, `ems_sync_age` |
| FortiClient EMS Identity Providers | Provider inventory, including an explicit empty result; `ems_idp_count` |
| FortiClient EMS Webfilter | Inventory plus imported-firewall sync alarms; `ems_webfilter_profiles`, `ems_webfilter_imports`, `ems_sync_age` (oldest active sync) |
| FortiClient EMS Webfilter Profile &lt;NAME&gt; | Name, activation, FortiGuard, category/URL counts and last update; `ems_webfilter_enabled`, `ems_webfilter_categories`, `ems_webfilter_urls` |
| FortiClient EMS Webfilter Import &lt;FIREWALL&gt; | Import-task activation, errors, last successful synchronization and age; `ems_sync_age` |

For Shared EMS, items carry a site prefix, for example
`FortiClient EMS ["customer-a-123"] License`; Global services use `["global"]`.
See the scope table above for where each service is collected.

Webfilter profile services use the profile name. Duplicate names within a site
receive an ID suffix; missing names fall back to the ID. Profiles marked
`is_default: true` do not create individual services, but remain counted in the
inventory summary. Profile presence or an enabled setting does not establish
endpoint assignment or active use.

IDP names use the connector alias, provider name, domain name or group path, in
that order. Numeric provider IDs are appended when available; GUIDs appear in
the service summary rather than its name. Connector IDs are not treated as unique
provider IDs. This supports EMS responses with an empty connector alias.
Providers with only a GUID use the display name `Unnamed provider`. The Identity
Providers inventory service explicitly reports empty lists and flags missing or
ambiguous identities as UNKNOWN rather than silently hiding them.

Historical graphs use Checkmk's normal recording from the start of monitoring.
Existing EMS history is not imported. Metric names use the `ems_` prefix to
avoid collisions with other Fortinet plugins. Each OS endpoint service contains
one graph for the total endpoint count (`ems_endpoints`). Installed FortiClient
versions and their counts appear dynamically in the OS service summary, for
example `5 endpoints, FortiClient 7.4.8.1977: 3, FortiClient 7.4.8.2066: 2`.
Counts are grouped by exact version, independent of API row order. New versions
appear on the next check without service discovery or code changes. No
per-version metrics or graphs are emitted. Existing total-count history is
preserved; previously recorded version metrics are no longer updated.

After updating from a package with separate `Endpoints <OS> Version ...`
services, run a full service discovery, remove the old version services and
activate the changes. The Windows and macOS endpoint services remain.

Graph definitions cover license seats and utilization, license/certificate
remaining days, endpoint totals, IDP devices/users, synchronization
progress/age, provider inventory, webfilter inventory/settings and auto-upgrade
status (1 = enabled, 0 = disabled). Hostname, serial
number and version are text values and have no numeric graph. Accept services
and start monitoring to record measurements; service discovery alone does not
populate historical graphs. A valid endpoint count of zero is still recorded.

### IDP and webfilter discovery troubleshooting

Providers with an empty `connection_info.alias` retain their domain/GUID for
discovery. After installing the
new package, activate changes and rescan the host to accept the IDP, Identity
Providers and Webfilter services. Existing license, certificate, endpoint and
System field services are unchanged.

A successful empty IDP list creates a zero-count inventory service, not a
fabricated provider. For `/api/v1/idps/index`, `result.retval: 1` without `data`
also means an empty inventory. Other missing or malformed data yields UNKNOWN.
Regression tests cover empty connector aliases and webfilter collection.
Webfilter service discovery has also been confirmed in a live Cloud Checkmk run.
Verify account permissions when configuring each deployment.

### Synchronization alarms and readable IDP names

**FortiClient EMS Webfilter** now includes the synchronization results of its
imported firewalls. The summary and individual **Webfilter Import** services
use the **FortiClient EMS webfilter** rule: default WARN at 24 hours and CRIT at
48 hours since the last successful synchronization. Select the `Webfilter`
service item to configure the summary, or match the import items to configure
individual tasks. Errors default to CRIT; disabled tasks default to WARN.
Missing or invalid sync data reports UNKNOWN. A healthy age of 0.0 hours is OK.
The summary exports the oldest enabled-task sync age only when all active tasks
have valid timestamps. With no imported tasks, there is no sync-age measurement.
The profile **Last update** timestamp remains informational.

IDP synchronization age uses the independent **FortiClient EMS identity providers**
rule, also defaulting to WARN/CRIT at 24/48 hours. Checkmk notification rules
determine whether and when these service states generate notifications.

IDP GUIDs now appear alongside the domain in service output. When updating from GUID-suffixed IDP names, rescan and accept the shorter IDP service names, then remove the vanished
GUID-suffixed services. Update any item-specific rules that matched the old names.
Duplicate provider display names produce UNKNOWN instead of merging data.

## Rules and defaults

| Rule | Default WARN / CRIT |
| --- | --- |
| FortiClient EMS auto upgrade | Enabled: WARN; disabled: WARN; independently configurable as OK, WARN or CRIT |
| FortiClient EMS licenses: utilization | At or above 80 / 90% |
| FortiClient EMS licenses: remaining lifetime | Below 30 / 14 days |
| FortiClient EMS certificate expiry | Below 30 / 14 days |
| FortiClient EMS identity providers: IDP offline | CRIT; configurable as WARN or CRIT |
| FortiClient EMS identity providers: connector offline | CRIT; configurable as WARN or CRIT |
| FortiClient EMS identity providers: synchronization error | CRIT; configurable as WARN or CRIT |
| Time since last successful synchronization | At or above 24 / 48 hours |
| FortiClient EMS webfilter: profile disabled | WARN; configurable as OK, WARN or CRIT |
| FortiClient EMS webfilter: import sync disabled | WARN; configurable as OK, WARN or CRIT |
| FortiClient EMS webfilter: import sync error | CRIT; configurable as WARN or CRIT |
| FortiClient EMS webfilter: import sync age | At or above 24 / 48 hours |

Rules can match service items to target a particular tenant or IDP. License rules
match `License` (with the tenant prefix for Shared EMS), regardless of product.
To accept enabled automatic upgrades, create a **FortiClient EMS auto upgrade**
rule matching `System Auto Upgrade` (with the tenant prefix for Shared EMS) and
set **Auto upgrade enabled** to **OK**. Save the rule and activate changes.
Existing rules without this setting use the default WARN state for enabled
automatic upgrades. The separate disabled-state setting remains unchanged.
Threshold evaluation can be disabled. Expired licenses/certificates and exceeded
license capacity still cause CRIT.

### License calculation

The single **FortiClient EMS License** service selects EPP, ZTNA or SASE from
nonzero assigned seats or usage and shows that product in its summary. A product
change updates the same service without discovery. Products with zero capacity
and usage are ignored, even if they have an expiry date. Multiple active products
are reported as UNKNOWN rather than combining their metrics. The selected
product maps the following fields (`ztna`, `epp` or `sase`):

| API field / calculation | Metric | Meaning |
| --- | --- | --- |
| `data.used.<type>` | `ems_license_used` | Used seats |
| On-Prem: `data.vdom_seats.<type>`; Cloud: `data.seats.<type>` | `ems_license_max` | Assigned seats |
| `used / maximum * 100` | `ems_license_utilization` | License utilization |
| Applicable expiry date minus current UTC date | `ems_remaining_days` | Remaining license lifetime |

For example, 80 used seats and a capacity of 100 produce 80% utilization,
reaching the default WARN threshold. Missing or invalid numeric fields produce
UNKNOWN. Zero capacity prevents percentage calculation: 0/0 reports no licensed
seats without a utilization metric, while any use with zero capacity is CRIT.

Periods whose type contains ZTNA, EPP or SASE apply to the corresponding product.
Unclassified or numeric types are treated as shared license periods. If several periods apply, the latest expiry is used
to account for renewals. Numeric product IDs are not mapped to guessed product
names. Deployments with other license mappings require a sanitized response
sample to validate their interpretation.

After updating from separate `License EPP`, `License ZTNA` and `License SASE`
services, run full service discovery, remove the old license services and accept
`License`, then activate changes. Update rules matching the old product-specific
items. Existing license history remains attached to the old service names and
is not migrated automatically.

The license seat graph shows **Assigned seats** (`ems_license_max`, green) and
**Used seats** (`ems_license_used`, blue) together, including zero values such as
2 assigned / 0 used. Its range includes the zero baseline and expands as needed.

### Certificate and synchronization lifetime

Certificate monitoring applies to On-Prem Dedicated and On-Prem Shared only.
Only certificates with a non-empty `assigned_to` value are monitored. The
earliest expiry among assigned certificates determines the remaining-days
metric. No assigned certificates or invalid expiry dates produce UNKNOWN.

Remaining days use the UTC calendar date. Synchronization age uses the full UTC
timestamp of the last successful synchronization. Missing timestamps and future
synchronization timestamps produce UNKNOWN.

## Metric units

| Metrics | Unit |
| --- | --- |
| `ems_license_used`, `ems_license_max`, `ems_endpoints`, `ems_idp_devices`, `ems_idp_users`, `ems_idp_count` | Count |
| `ems_webfilter_profiles`, `ems_webfilter_imports`, `ems_webfilter_categories`, `ems_webfilter_urls` | Count |
| `ems_license_utilization`, `ems_sync_progress` | Percent |
| `ems_remaining_days` | Whole UTC calendar days |
| `ems_sync_age` | Seconds; check summaries render hours |
| `ems_auto_upgrade_enabled`, `ems_webfilter_enabled` | Count used as a boolean: 1 = enabled, 0 = disabled |

Endpoint totals sum the non-negative integer `value` fields returned for that OS.
Version counts group those rows by the exact `name` field. Missing/empty version
names, invalid counts or fractional counts make the check UNKNOWN. Counts have no default WARN/CRIT levels. IDP synchronization
progress is informational; availability, errors and sync age determine alarms.
FortiGuard enabled/disabled is informational; a missing or invalid flag is UNKNOWN.
System Package Region is also text and has no numeric graph.
