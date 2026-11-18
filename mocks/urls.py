from django.urls import re_path

from .apis import content, fallback, proxy, rules, runtime, system

# first match wins. Exact paths stay exact, the admin api tolerates a trailing slash.
# Whatever no route claims (and /api/send, /api/version, /rule-content with the wrong
# method) is the rule engine's: that is how /api/users can be mocked.
urlpatterns = [
    re_path(r"^health$", system.health),
    re_path(r"^(?:ui)?$", system.ui),
    re_path(r"^ca\.(?:pem|crt)$", system.ca_pem),
    re_path(r"^api/send$", system.send),
    re_path(r"^api/proxy/decide$", proxy.proxy_decide),
    re_path(r"^api/proxy/seen$", proxy.proxy_seen),
    re_path(r"^api/version(?:/.*)?$", system.version),
    re_path(r"^api/mock-state(?:/.*)?$", runtime.mock_state),
    re_path(r"^api/metrics/?$", runtime.metrics),
    re_path(r"^api/metrics/reset/?$", runtime.metrics_reset),
    re_path(r"^api/rules/?$", rules.rules),
    re_path(r"^api/rules/(?P<name>[^/]+)/?$", rules.rule_item),
    re_path(r"^api/rules/(?P<name>[^/]+)/toggle/?$", rules.rule_toggle),
    re_path(r"^api/history/?$", rules.history),
    re_path(r"^api/history/(?P<ident>[^/]+)/restore/?$", rules.history_restore),
    re_path(r"^api/rule-content/?$", content.content_list),
    re_path(r"^api/rule-content/(?P<name>[^/]+)/?$", content.content_item),
    re_path(
        r"^api/(?:mock-state|metrics|rules|history|rule-content|proxy)(?:/.*)?$",
        proxy.no,
    ),
    re_path(r"^rule-content/(?P<name>.*)$", content.content_serve),
    re_path(r"^", fallback.mock),
]
