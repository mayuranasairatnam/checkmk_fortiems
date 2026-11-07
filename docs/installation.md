# Installation and configuration

[← README](../README.md) · [Installation](installation.md) · [Authentication](authentication.md) · [Monitoring](monitoring.md) · [Development](development.md)

## Requirements

- Checkmk **2.4 or 2.5**, with Python **3.11+** and `requests` in the site environment.
- HTTPS access from the Checkmk site to the EMS server or `forticlient.forticloud.com`.
- An EMS account or FortiCloud Access Key with the [required permissions](authentication.md).

## Install the package

Download the MKP using **Download MKP** in the [README](../README.md), then upload
and enable it under **Setup → Maintenance → Extension packages**. The package ID
is `check_fortiems`. No Checkmk agent is required on the monitored system.

Alternatively, as the Checkmk site user, replace `VERSION` with the downloaded
package version:

```sh
mkp add /path/to/check_fortiems-VERSION.mkp
mkp enable check_fortiems VERSION
```

To build locally, run `python3 -B build_mkp.py` from the repository directory.
See [development](development.md) for local setup and checks.

## Configure the host and rule

1. Create an EMS host. For On-Prem, use the EMS server's DNS name or IP
   address. For Cloud, select **No IP**; the gateway address is fixed.
   Select **Configured API integrations, no Checkmk agent** as the data source.
2. In **Setup**, search for **FortiClient EMS** and open the integration ruleset.
   Create a new rule and restrict its **Conditions → Explicit hosts** to the
   host created above.
3. Select **Deployment type** and enter the matching credentials:

   | Deployment type | Required fields |
   | --- | --- |
   | **On-prem Dedicated** (default) | **Authentication method**, **Username**, **Password**, **Site** |
   | **On-prem Shared** | **Authentication method**, **Username**, **Password**; optional **Sites to monitor (plus global)** |
   | **Cloud** | **FortiCloud account email** and **FortiCloud Access Key** |

   For On-Prem, **RADIUS login** is the default authentication method; select
   **Local login** for a local EMS account. Use the Checkmk Password Store for
   passwords and Access Keys.
4. For On-Prem, enter exact lowercase site names. An empty Shared site list
   monitors all discovered sites plus Global. Cloud has no site selection.
   See [site selection](#on-prem-dedicated-and-shared-site-selection).
5. Review the [connection settings](#connection-settings), then save the rule.
6. Activate changes and continue with [service discovery](#discover-and-check-services).

## Connection settings

| Setting | Default / behavior |
| --- | --- |
| On-Prem target address | Checkmk host primary address; falls back to the host name |
| Cloud gateway | Fixed to `https://forticlient.forticloud.com`; ignores the host address and On-Prem port |
| HTTPS port | 443; applies to On-Prem |
| Timeout per API request | 30 seconds |
| TLS certificate verification | Enabled; uses the Python environment's default trust store |

For On-Prem, the certificate must match the target address. There is no separate
host override. See [authentication](authentication.md) for permissions.

## Discover and check services

Run service discovery on the host, accept the discovered services and activate
changes. Inspect **FortiClient EMS API** for collection errors. After changing the
monitoring scope, rescan the host and use **Remove vanished services** for items
that are no longer monitored.

New On-Prem sites and identity providers appear during normal service discovery.
Configure periodic service discovery if new services should be accepted
automatically. Removed objects can remain UNKNOWN until their vanished services
are removed.

As the Checkmk site user, run discovery and check the result:

```sh
cmk -vI YOUR_HOST
cmk -nv YOUR_HOST
```

### Standalone agent check

For a standalone API test, the agent can read its password from stdin:

```sh
python3 cmk_addons_plugins/fortiems/libexec/agent_fortiems \
  --address ems.example.org --user monitoring --site default \
  --auth-method radius --password-stdin
```

Use `--auth-method local` for a local account. For Shared EMS, add `--shared`
and optionally repeat `--tenant customera` with the exact lowercase site name.
For Cloud, use the Access Key on stdin:

```sh
python3 cmk_addons_plugins/fortiems/libexec/agent_fortiems \
  --cloud --account-email monitoring@example.org --access-key-stdin
```

Supply secrets through stdin for terminal tests. Use the Checkmk rule for production.
See [authentication](authentication.md) for permissions, session behavior and
errors, and [monitoring](monitoring.md) for services, thresholds and graphs.

## On-Prem Dedicated and Shared site selection

**Always enter site names in lowercase**, for example `default`, `customera` or
`customerb`. Use the exact lowercase site name configured in EMS for both
**Site** and **Sites to monitor (plus global)**.

**On-Prem Dedicated** is the default deployment type. **Site**
defaults to `default`. Enter a different exact site name to monitor that site
through a direct login, if the EMS account supports it.

For **On-Prem Shared**, login sends only username and password without a site
binding. Cloud uses account email and Access Key without site selection. In On-Prem Shared
mode, the optional **Sites to monitor (plus global)** list selects exact customer
site names. If the list is empty or disabled, all sites
returned by discovery are monitored, including `default`; only `global` is
excluded from the site list because it is collected separately for global
system monitoring. Customer names do not need to match a naming pattern.
Global monitoring is always included in Shared mode, including when an exact
site allowlist is configured.

For example, select `customer-a-123` and
`customer-b-456` to monitor those tenants. To monitor only one customer, specify
one entry in the Shared list, or use Dedicated with a direct site login where
supported.

Site selection is case-sensitive; enter `customera` or `customerb` exactly as configured
in EMS, using lowercase throughout.
A configured site missing from discovery produces an API error listing the
discovered customer sites while available selected sites remain monitored.
If discovery returns no monitoring sites after excluding `global`, the
API service reports CRIT. Check deployment mode and account site access; use
Dedicated to monitor `default` directly. Tenant switching is sequential. After a failed
switch, the agent skips that tenant's queries so data from the preceding site
cannot be attributed to it. Failed tenant discovery never falls back to
monitoring `default`.

### Existing rules and services

Updating the package preserves saved site selections and migrates the previous
flat deployment settings into the conditional deployment form. Existing Dedicated
and Shared rules remain On-Prem and retain their credentials and selections. The removed
host override is ignored; verify the address configured on the Checkmk host. Rules saved before the
authentication selector was introduced continue to use RADIUS. Select **Local
login** explicitly to use a local EMS account. Changing the login site,
deployment type or Shared selection requires saving the rule, activating changes
and running discovery. Use **Remove vanished services** to remove services for
sites or objects that are no longer monitored.

For On-Prem, system information is discovered as **System Hostname**,
**System Serial Number**, **System Version** and **System Auto Upgrade**. After updating the MKP,
activate changes, rescan the host, accept these four services and remove the
vanished combined **FortiClient EMS System** service. Existing rules matching
only the old `System` item must be adjusted to `System Auto Upgrade` to configure
the auto-upgrade states. Shared items retain their tenant prefix.
For Cloud, **System Serial Number**, **System Version** and **System Package Region**
are discovered. After updating an existing Cloud host, rescan and use
**Remove vanished services** to remove old Hostname, Auto Upgrade and
Certificates services.

The plugin includes **FortiClient EMS System Package Region**. Rescan the host to
discover it. This text service displays **Cloud Region to Repackage Installers**
from the existing server settings query, without an additional API request. A
non-empty region reports OK; a missing or invalid region reports UNKNOWN. Shared
deployments include the tenant prefix. No numeric metric is created for a region.
