"""
Namespaced FortiClient EMS metrics and historical graph definitions.

OS endpoint services graph the total endpoint count.
Version distribution is displayed dynamically in each OS service summary.
"""
from cmk.graphing.v1 import Title
from cmk.graphing.v1.metrics import AutoPrecision, Color, DecimalNotation, Metric, StrictPrecision, Unit
from cmk.graphing.v1.graphs import Graph, MinimalRange

COUNT = Unit(DecimalNotation(''), StrictPrecision(0))
PERCENT = Unit(DecimalNotation('%'), AutoPrecision(1))
DAYS = Unit(DecimalNotation('days'), StrictPrecision(0))
SECONDS = Unit(DecimalNotation('s'), AutoPrecision(0))

metric_ems_license_used = Metric(name='ems_license_used', title=Title('Used seats'), unit=COUNT, color=Color.BLUE)
metric_ems_license_max = Metric(name='ems_license_max', title=Title('Assigned seats'), unit=COUNT, color=Color.GREEN)
metric_ems_license_utilization = Metric(name='ems_license_utilization', title=Title('License utilization'), unit=PERCENT, color=Color.BLUE)
metric_ems_remaining_days = Metric(name='ems_remaining_days', title=Title('Remaining lifetime'), unit=DAYS, color=Color.ORANGE)
metric_ems_endpoints = Metric(name='ems_endpoints', title=Title('Endpoints'), unit=COUNT, color=Color.BLUE)
metric_ems_idp_devices = Metric(name='ems_idp_devices', title=Title('IDP devices'), unit=COUNT, color=Color.BLUE)
metric_ems_idp_users = Metric(name='ems_idp_users', title=Title('IDP users'), unit=COUNT, color=Color.GREEN)
metric_ems_sync_progress = Metric(name='ems_sync_progress', title=Title('Synchronization progress'), unit=PERCENT, color=Color.BLUE)
metric_ems_sync_age = Metric(name='ems_sync_age', title=Title('Time since successful sync'), unit=SECONDS, color=Color.ORANGE)
metric_ems_auto_upgrade_enabled = Metric(name='ems_auto_upgrade_enabled', title=Title('Auto upgrade enabled (1 = enabled, 0 = disabled)'), unit=COUNT, color=Color.GREEN)
metric_ems_idp_count = Metric(name='ems_idp_count', title=Title('Identity providers'), unit=COUNT, color=Color.BLUE)
metric_ems_webfilter_profiles = Metric(name='ems_webfilter_profiles', title=Title('Webfilter profiles'), unit=COUNT, color=Color.BLUE)
metric_ems_webfilter_imports = Metric(name='ems_webfilter_imports', title=Title('Imported firewalls'), unit=COUNT, color=Color.GREEN)
metric_ems_webfilter_enabled = Metric(name='ems_webfilter_enabled', title=Title('Webfilter enabled (1/0)'), unit=COUNT, color=Color.GREEN)
metric_ems_webfilter_categories = Metric(name='ems_webfilter_categories', title=Title('Webfilter categories'), unit=COUNT, color=Color.BLUE)
metric_ems_webfilter_urls = Metric(name='ems_webfilter_urls', title=Title('Webfilter URL entries'), unit=COUNT, color=Color.GREEN)

graph_fortiems_license = Graph(name='fortiems_license', title=Title('FortiClient EMS assigned and used license seats'),
                                simple_lines=['ems_license_max', 'ems_license_used'],
                                minimal_range=MinimalRange(0, 1))
graph_fortiems_utilization = Graph(name='fortiems_utilization', title=Title('FortiClient EMS license utilization'), simple_lines=['ems_license_utilization'], minimal_range=MinimalRange(0, 100))
graph_fortiems_lifetime = Graph(name='fortiems_lifetime', title=Title('FortiClient EMS remaining lifetime'), simple_lines=['ems_remaining_days'])
graph_fortiems_endpoints = Graph(name='fortiems_endpoints', title=Title('FortiClient endpoints'), simple_lines=['ems_endpoints'])
graph_fortiems_idp = Graph(name='fortiems_idp', title=Title('FortiClient EMS identity provider'), simple_lines=['ems_idp_devices', 'ems_idp_users'])
graph_fortiems_sync_progress = Graph(name='fortiems_sync_progress', title=Title('FortiClient EMS synchronization progress'), simple_lines=['ems_sync_progress'], minimal_range=MinimalRange(0, 100))
graph_fortiems_sync_age = Graph(name='fortiems_sync_age', title=Title('FortiClient EMS synchronization age'), simple_lines=['ems_sync_age'])
graph_fortiems_auto_upgrade = Graph(name='fortiems_auto_upgrade', title=Title('FortiClient EMS auto upgrade status'), simple_lines=['ems_auto_upgrade_enabled'], minimal_range=MinimalRange(0, 1))
graph_fortiems_idp_count = Graph(name='fortiems_idp_count', title=Title('Identity providers'), simple_lines=['ems_idp_count'])
graph_fortiems_webfilter = Graph(name='fortiems_webfilter', title=Title('Webfilter inventory'), simple_lines=['ems_webfilter_profiles', 'ems_webfilter_imports'])
graph_fortiems_webfilter_enabled = Graph(name='fortiems_webfilter_enabled', title=Title('Webfilter activation'), simple_lines=['ems_webfilter_enabled'], minimal_range=MinimalRange(0, 1))
graph_fortiems_webfilter_entries = Graph(name='fortiems_webfilter_entries', title=Title('Webfilter categories and URLs'), simple_lines=['ems_webfilter_categories', 'ems_webfilter_urls'])
