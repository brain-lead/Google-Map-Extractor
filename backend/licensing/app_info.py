"""
GME (Google Map Extractor) - Application Information
Centralized application metadata, branding, and Brain Lead licensing endpoints.
"""

# Application Details
APP_NAME = "Google_Map_Extractor"
APP_VERSION = "3.0"
APP_ID = "Google Map Extractor"  # Keep canonical server software identifier for existing keys
APP_DISPLAY_NAME = "GME — Google Map Extractor"
APP_DESCRIPTION = "GME (Google Map Extractor) — Google Maps business data extractor with built-in lead scoring"

# Developer & Company Branding (Official Brain Lead Identity)
DEVELOPER = "Brain Lead"
DEVELOPER_TELEGRAM = "@brain_lead"
DEVELOPER_CONTACT = "https://t.me/brain_lead"
DEVELOPER_BOT = "@brainleadbot"
TELEGRAM_BOT_URL = "https://t.me/BrainLeadBot"

# Website & Store URLs
WEBSITE_URL = "https://brainlead.dev"
BUY_LICENSE_URL = "https://t.me/BrainLeadBot"

# Backend Configuration (Brain Lead server)
BACKEND_URL = "https://brainlead.dev"
HWID_ENDPOINT = f"{BACKEND_URL}/check-hwid"
NOTIFICATION_ENDPOINT = f"{BACKEND_URL}/get-notifications-v2"
RESET_ENDPOINT = f"{BACKEND_URL}/reset-user"
RESET_BINDING_USER_ENDPOINT = f"{BACKEND_URL}/reset-license-binding-user"
ADMIN_NOTIFICATION_KEY = "UAUQ-1OEI-L1PV-FO7Y"

# License Configuration
DEFAULT_USERNAME = "licence_trial_google_map"
LICENSE_PREFIX = "licence_braintools"
CAMPAIGN_USERNAME = "campaign_braintools"

# Free-tier limits (applied when no valid license key is present)
FREE_MAX_RESULTS_PER_SEARCH = 50
FREE_AREA_SCAN_MAX_TILES = 4

# Terms and Build Information
TERMS_VERSION = "2.0"
BUILD_DATE = "2026-11-19"
RELEASE_TYPE = "Stable"
ADD_TODAY_DATE = True

# Optional white-label toggle ("" = public Brain Lead build, "Maker" = private client build)
notink = ""


def get_app_info():
    """Get complete application information as dictionary."""
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "app_id": APP_ID,
        "display_name": APP_DISPLAY_NAME,
        "description": APP_DESCRIPTION,
        "developer": DEVELOPER,
        "contact": DEVELOPER_TELEGRAM,
        "website": WEBSITE_URL,
        "build_date": BUILD_DATE,
        "release_type": RELEASE_TYPE,
        "add_today_date": ADD_TODAY_DATE,
        "notink": notink,
    }


def get_backend_config():
    """Get backend configuration."""
    return {
        "backend_url": BACKEND_URL,
        "hwid_endpoint": HWID_ENDPOINT,
        "notification_endpoint": NOTIFICATION_ENDPOINT,
        "reset_endpoint": RESET_ENDPOINT,
        "reset_binding_endpoint": RESET_BINDING_USER_ENDPOINT,
        "admin_notification_key": ADMIN_NOTIFICATION_KEY,
        "default_username": DEFAULT_USERNAME,
        "license_prefix": LICENSE_PREFIX,
    }


def get_version_string():
    """Get formatted version string."""
    return f"{APP_NAME} v{APP_VERSION}"


def get_user_agent():
    """Get user agent string for API requests."""
    return f"{APP_ID}/{APP_VERSION}"
