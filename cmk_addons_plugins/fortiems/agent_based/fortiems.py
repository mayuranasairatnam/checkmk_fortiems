"""
Compatibility imports for FortiClient EMS checks created before the module split.

Implementations and registrations live in the feature modules. Historical
attributes are resolved on demand so existing compiled imports keep working,
without exposing duplicate registrations during plugin discovery.
"""
from . import fortiems_api as _api
from . import fortiems_system as _system
from . import fortiems_license as _license
from . import fortiems_certificates as _certificates
from . import fortiems_endpoints as _endpoints
from . import fortiems_idp as _idp
from . import fortiems_webfilter as _webfilter
from ..lib import common as _common


_EXPORTS = {
    'agent_section_fortiems': _api.agent_section_fortiems,
    'check_api': _api.check_api,
    'check_certificates_data': _certificates.check_certificates_data,
    'check_endpoints_data': _endpoints.check_endpoints_data,
    'check_idp_data': _idp.check_idp_data,
    'check_license_data': _license.check_license_data,
    'check_plugin_fortiems_api': _api.check_plugin_fortiems_api,
    'check_plugin_fortiems_certificates': _certificates.check_plugin_fortiems_certificates,
    'check_plugin_fortiems_endpoints': _endpoints.check_plugin_fortiems_endpoints,
    'check_plugin_fortiems_idp': _idp.check_plugin_fortiems_idp,
    'check_plugin_fortiems_idp_summary': _idp.check_plugin_fortiems_idp_summary,
    'check_plugin_fortiems_webfilter': _webfilter.check_plugin_fortiems_webfilter,
    'check_plugin_fortiems_webfilter_profiles': _webfilter.check_plugin_fortiems_webfilter_profiles,
    'check_plugin_fortiems_webfilter_imports': _webfilter.check_plugin_fortiems_webfilter_imports,
    'check_plugin_fortiems_license': _license.check_plugin_fortiems_license,
    'check_plugin_fortiems_system': _system.check_plugin_fortiems_system,
    'check_plugin_fortiems_tenant_api': _api.check_plugin_fortiems_tenant_api,
    'check_system_data': _system.check_system_data,
    'check_tenant_api_data': _api.check_tenant_api_data,
    'checking': _common.checking,
    'configured_state': _common.configured_state,
    'discover_api': _api.discover_api,
    'discovery': _common.discovery,
    'endpoint_counts': _endpoints.endpoint_counts,
    'expiry_results': _common.expiry_results,
    'flag': _common.flag,
    'label': _common.label,
    'moment': _common.moment,
    'number': _common.number,
    'objects': _common.objects,
    'parse_fortiems': _api.parse_fortiems,
    'remaining': _common.remaining,
}


def __getattr__(name):
    """
    Resolve a historical helper, callback or plugin registration by name.

    Input:
        name: Attribute imported from the previous combined module.
    Output:
        Original object from its feature module; raises AttributeError otherwise.
    """
    try:
        return _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
