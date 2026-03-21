# Seafile seahub_settings.py — OAuth2 / Authentik SSO section
# Append this to /shared/seafile/conf/seahub_settings.py inside the seafile container
# Then restart: docker restart seafile
#
# Prerequisites:
#   1. Create OAuth2/OIDC provider in Authentik (slug: "seafile")
#   2. Set redirect URI to https://seafile.tustin.house/oauth/callback/
#   3. Copy Client ID and Client Secret below

# === OAuth2 / Authentik SSO ===
ENABLE_OAUTH = True
OAUTH_CREATE_UNKNOWN_USER = True
OAUTH_ACTIVATE_USER_AFTER_CREATION = True

OAUTH_CLIENT_ID = "<your-authentik-client-id>"
OAUTH_CLIENT_SECRET = "<your-authentik-client-secret>"
OAUTH_REDIRECT_URL = "https://seafile.tustin.house/oauth/callback/"

OAUTH_PROVIDER_DOMAIN = "auth.tustin.house"
OAUTH_PROVIDER = "authentik"

OAUTH_AUTHORIZATION_URL = "https://auth.tustin.house/application/o/authorize/"
OAUTH_TOKEN_URL = "https://auth.tustin.house/application/o/token/"
OAUTH_USER_INFO_URL = "https://auth.tustin.house/application/o/userinfo/"

OAUTH_SCOPE = ["openid", "profile", "email"]

OAUTH_ATTRIBUTE_MAP = {
    "email": (True, "contact_email"),
    "name": (False, "name"),
    "sub": (True, "uid"),
}
