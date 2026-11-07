# Authentication and API access

[← README](../README.md) · [Installation](installation.md) · [Authentication](authentication.md) · [Monitoring](monitoring.md) · [Development](development.md)

See the [authentication comparison](../README.md#authentication-methods) for supported services.

## Required account and permissions

Use a dedicated monitoring account that can use the selected login method and read
all required API endpoints. Shared EMS additionally requires permission to list
sites and switch to each monitored tenant. Restricted API access is reported as
an error. Verify permissions for the EMS version and deployment in use.

### On-Prem login and session lifecycle

Configure the account's username and password in the **FortiClient EMS**
rule. The required **Authentication method** field selects the login endpoint:

| Method | Login endpoint |
| --- | --- |
| RADIUS login (default) | `POST /api/v1/auth/radius` |
| Local login | `POST /api/v1/auth/signin` |

In Dedicated mode, both methods send the following body (placeholder credentials):

```json
{
  "name": "svc.monitoring",
  "password": "<password>",
  "site": "default"
}
```

Shared mode omits the `site` key at login. After login, it discovers customer sites and switches to each site.

The selected method applies to both On-Prem Dedicated and On-Prem Shared deployments. Existing
rules retain RADIUS authentication. The agent uses only the selected method and
does not retry another method when login fails. A standalone diagnostic confirmed
Local login, site discovery and the switch to `customera` against the maintainer's EMS;
the plugin implementation is covered by offline regression tests.

Local login first loads the EMS root page (`GET /`). If it sets a `csrftoken`
cookie, signin includes the matching `x-csrftoken` header. If the root page sets
no cookie, signin proceeds without a CSRF header, matching the successful live
diagnostic. Signin sends `Origin` in both cases. The cookie is required only
after login, and all later API requests use the current cookie and CSRF header.
No cookie or token values are hardcoded. RADIUS does not require this extra GET.

The login must leave a non-empty `csrftoken` cookie. The client retains session
cookies and sends the current token in the `x-csrftoken` header on subsequent
requests. Regular monitoring requests use `ems-call-type: 2`. Shared site
discovery uses `ems-call-type: 1`.

A failed login stops collection and appears in the API service. Existing
services without data become UNKNOWN. The local HTTP session is always closed
in `finally`. On-Prem server-side logout is not implemented because no logout
endpoint was provided; EMS controls that session timeout. Cloud logout is explicit.

### FortiCloud EMS authentication

Configure your **account email** and **Access Key** in the Checkmk **FortiClient
EMS** Cloud rule. The plugin performs login, API requests and logout
automatically using the following workflow.

#### 1. Log in

Send `POST` to:

```text
https://forticlient.forticloud.com/fct/api/public/v1/ems_api_cloud/login/
```

JSON body:

```json
{
  "access_key": "<access-key>",
  "account_email": "<account-email>"
}
```

A successful response provides the session ID:

```json
{
  "result": "login",
  "session_id": "<session-id>"
}
```

#### 2. Call the EMS API

Append the EMS API path to the gateway URL:

```text
https://forticlient.forticloud.com/fct/api/public/v1/ems_api<EMS_API_PATH>
```

For example, `/api/v1/system/serial_number` becomes:

```text
https://forticlient.forticloud.com/fct/api/public/v1/ems_api/api/v1/system/serial_number
```

Use the method and parameters required by the EMS endpoint. Include these
headers, using the session ID returned at login without a `Bearer` prefix:

```http
Authorization: <session-id>
Ems-Api-Header-Content-Type: application/json
```

#### 3. Log out

Send `POST` to:

```text
https://forticlient.forticloud.com/fct/api/public/v1/ems_api_cloud/logout/
```

Include this header:

```http
Authorization: <session-id>
```

The plugin attempts logout after collection, including after a failed query,
and closes its local HTTP session. Logout errors are reported without discarding
collected data. Keep the Access Key and session ID private.

Cloud does not support tenants. The agent queries the EMS instance associated
with the Access Key directly, without site discovery, site selection or session
switching. The Cloud rule only asks for account email and Access Key.
Certificate scanning is disabled for Cloud: the certificate endpoint is not queried
and no Certificates service is discovered. On-Prem retains certificate monitoring.
No on-prem password, CSRF cookie or IP address is used for Cloud authentication.
Access Keys and session IDs are not exported in the agent section.

Cloud uses instance-wide license capacity from `license.data.seats`, together with
`used` for consumption and utilization graphs. On-Prem continues to use
`vdom_seats` for site capacity.

Cloud discovers System Serial Number, System Version and System Package Region.
Hostname and Auto Upgrade services are omitted because Cloud system
responses do not expose those fields. Cloud requests `/api/v1/system/consts/get`
with both `system_update_time` and `vdom_update_time` set to the initial
synchronization baseline `1970-01-01T00:00:00`, since Cloud system information
has no `system_time`. Requests without these parameters returned HTTP 500
during live testing. On-Prem continues to use its system timestamps. The gateway request
using this initial baseline has been confirmed live: **System Version** reports
`7.4.7.2194` and the API service is OK. A failed version query remains an API error.
Endpoint services show installed FortiClient versions and their counts in each OS summary, with a graph for the total endpoint count.

Cloud login/logout and endpoint shapes were checked with a live diagnostic.
The subsequent Checkmk run confirmed successful collection and the expected
license, system, endpoint, IDP and webfilter services. Offline regression tests
cover these response shapes and error paths.

### API endpoints

The paths below are relative to EMS. Cloud sends supported paths through the
`/fct/api/public/v1/ems_api` gateway prefix. Cloud login/logout use the separate
endpoints documented above.

| Method | EMS API path | Purpose | On-Prem Dedicated | On-Prem Shared | Cloud |
| --- | --- | --- | --- | --- | --- |
| POST | `/api/v1/auth/radius` | RADIUS login | Yes | Yes | No |
| POST | `/api/v1/auth/signin` | Local login | Yes | Yes | No |
| GET | `/api/v1/sites/index` | Site discovery | No | Yes | No |
| POST | `/api/v1/session/update` | Site/Global switch | No | Yes | No |
| GET | `/api/v1/system/info?is_basic=true` | System data; Cloud returns account metadata | Yes | Global | Yes |
| GET | `/api/v1/system/consts/get` | EMS server version; On-Prem uses system timestamps; Cloud uses an initial sync baseline | Yes | Global | Yes |
| GET | `/api/v1/settings/server/get` | Package region; On-Prem also provides auto-upgrade settings | Yes | Global and per site | Yes |
| GET | `/api/v1/license/get` | License seats, usage, periods and serial number | Yes | Global and per site | Yes |
| GET | `/api/v1/server_certificates/index` | Assigned certificate expiry | Yes | Global | No |
| GET | `/api/v1/idps/index` | IDP, connector and synchronization status | Yes | Per site | Yes |
| GET | `/api/v1/profiles/webfilter/index` | Profile inventory and firewall sync tasks | Yes | Per site | Yes |
| GET | `/api/v1/profiles/webfilter/<ID>/get` | Settings and counts for each unique profile | Yes | Per site | Yes |
| GET | `/api/v1/endpoints/fctversionwindows/donut` | Windows endpoint version counts | Yes | Per site | Yes |
| GET | `/api/v1/endpoints/fctversionmac/donut` | macOS endpoint version counts | Yes | Per site | Yes |

API data must use the expected JSON envelope and data container type. Explicit
API failures, invalid JSON and missing data containers are rejected. Missing or
invalid individual measurements produce UNKNOWN in the affected checks.

## Error handling and password protection

- Configure credentials in the **FortiClient EMS** rule. Checkmk supplies
  the password or Access Key through a secret reference; credentials are not embedded in files.
- Plaintext passwords are not passed in process arguments. Only required
  monitoring fields are exported; Access Keys, session tokens and full server settings stay
  out of agent output.
- HTTP, TLS, timeout, authentication, JSON and API errors appear in the API
  service. Missing or invalid measurements produce UNKNOWN without fabricated
  zero measurements.
- Successful partial queries remain available when another query or tenant fails.
- A successfully retrieved empty endpoint distribution is a valid zero count.
- TLS verification is enabled by default and can be explicitly disabled.
- Redirects are not followed. Environment proxies are ignored.

Reads and site switches retry transient connection failures, timeouts and HTTP
429/502/503/504 at most three times, with waits of 0.5 and 1 second. Login POSTs,
TLS errors and HTTP 401/403 are not retried.

The timeout applies per request. An On-Prem Dedicated run makes **10 + P requests**,
where P is the number of unique webfilter profile IDs. An On-Prem Shared run makes
**8 + 7 × number of monitored sites + total profile requests** when
collection succeeds. Requests run sequentially. Configure Checkmk's data source time limit
to accommodate the tenant count and request timeout. Local authentication adds
one request to load the login page and establish the CSRF cookie. A Cloud run
makes **10 + P requests**, including login, constants and logout, without
certificate scans, site discovery or switching. Counts exclude retries.
