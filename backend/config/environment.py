"""Keep local development settings out of the production image configuration."""
import os
import sys
from pathlib import Path
from dotenv import dotenv_values, load_dotenv

LLM_KEYS = {
    'LLM_ENABLED', 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY',
    'LLM_TIMEOUT', 'LLM_MAX_TOKENS', 'LLM_JSON_MODE',
    'GOOGLE_MAPS_BROWSER_KEY', 'NESHAN_MAP_KEY', 'NESHAN_SERVICE_KEY', 'SERPER_API_KEY', 'GOOGLE_PLACES_API_KEY',
    'WEB_RESEARCH_ENABLED', 'WEB_PAGE_FETCH_ENABLED', 'RESEARCH_TIMEOUT', 'PUBLISH_PHONE_CONTACTS',
    'AGENT_MAX_STEPS','AGENT_MAX_TOOLS','AGENT_DEADLINE_SECONDS','AGENT_MODEL_TIMEOUT','AGENT_STATE_TTL',
}
PLACEHOLDERS = {'paste_your_boxapi_key_here', 'your_api_key', 'your_boxapi_api_key'}


def load_environment(root):
    if os.getenv('TOROB_IN_DOCKER', '').lower() != 'true':
        load_dotenv(Path(root) / '.env', override=False)
        return
    # Console/exec commands must use the same paths as PID 1, including no-disk mode.
    if os.getenv('TOROB_BUILDING_IMAGE', '').lower() != 'true' and (Path(root) / 'scripts/container_start.py').is_file():
        script_path = str(Path(root) / 'scripts')
        if script_path not in sys.path:
            sys.path.insert(0, script_path)
        from container_start import configure_environment
        configure_environment(Path(root))
    # This private server file is never copied into the frontend build.
    source = Path(os.getenv('TOROB_ENV_FILE', str(Path(root) / 'config/runtime.env')))
    if not source.is_file():
        return
    file_first = os.getenv('SERVICE_CONFIG_SOURCE',os.getenv('LLM_CONFIG_SOURCE', 'file')).lower() != 'environment'
    for name, value in dotenv_values(source).items():
        if name not in LLM_KEYS or value is None:
            continue
        current = os.getenv(name, '').strip()
        if file_first or not current or (name == 'LLM_API_KEY' and current.lower() in PLACEHOLDERS):
            os.environ[name] = value

