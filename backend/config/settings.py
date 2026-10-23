import os
from pathlib import Path
from .environment import load_environment
from .runtime import secret_key

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
load_environment(ROOT_DIR)
DEBUG = os.getenv('DJANGO_DEBUG', 'true').lower() == 'true'
SECRET_KEY = secret_key(debug=DEBUG)
ALLOWED_HOSTS = [x.strip() for x in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1],testserver').split(',') if x.strip()]
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'corsheaders', 'shopping',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':[
    'django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages'
]}}]
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'
DATABASES = {'default':{'ENGINE':'django.db.backends.sqlite3','NAME':os.getenv('DJANGO_DB_PATH',str(BASE_DIR/'db.sqlite3')),'OPTIONS':{'timeout':30}}}
DATABASE_READONLY = os.getenv('DJANGO_DB_READONLY','false').lower() == 'true'
if DATABASE_READONLY:
    DATABASES['default']['NAME'] = Path(os.environ['DJANGO_DB_PATH']).resolve().as_uri()+'?mode=ro&immutable=1'
    DATABASES['default']['OPTIONS']['uri'] = True
    SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR/'staticfiles'
WHITENOISE_ROOT = ROOT_DIR/'dist'
WHITENOISE_INDEX_FILE = True
STORAGES = {'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CORS_ALLOWED_ORIGINS = [x.strip() for x in os.getenv('DJANGO_CORS_ORIGINS','http://localhost:4173,http://127.0.0.1:4173').split(',') if x.strip()]
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', ','.join(CORS_ALLOWED_ORIGINS)).split(',') if x.strip()]
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES':['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_AUTHENTICATION_CLASSES':[],
    'DEFAULT_PERMISSION_CLASSES':['rest_framework.permissions.AllowAny'],
    'DEFAULT_THROTTLE_CLASSES':['rest_framework.throttling.AnonRateThrottle'],
    'DEFAULT_THROTTLE_RATES':{'anon':'60/min','chat':'15/min','live':'12/min'},
}
CACHES = {'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache','LOCATION':'torob-yar'}}
DATA_UPLOAD_MAX_MEMORY_SIZE = 100_000
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT','true').lower() == 'true'
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Set SECURE_PROXY_SSL_HEADER only behind a trusted reverse proxy.
    if os.getenv('TRUST_PROXY_HTTPS') == 'true':
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO','https')
LLM_ENABLED = os.getenv('LLM_ENABLED','true').lower() == 'true'
LLM_BASE_URL = os.getenv('LLM_BASE_URL','https://ai.boxapi.ir/ai/v1').strip().rstrip('/')
LLM_API_KEY = os.getenv('LLM_API_KEY','').strip()
LLM_MODEL = os.getenv('LLM_MODEL','prism-ml/ternary-bonsai-2-27b').strip()
# Two bounded calls per chat: preference extraction and product analysis.
LLM_TIMEOUT = min(60, max(3, int(os.getenv('LLM_TIMEOUT','45'))))
LLM_MAX_TOKENS = min(4000, max(600, int(os.getenv('LLM_MAX_TOKENS','2200'))))
LLM_JSON_MODE = os.getenv('LLM_JSON_MODE','false').lower() == 'true'
TOROB_LIVE_ENABLED = os.getenv('TOROB_LIVE_ENABLED','true').lower() == 'true'
TOROB_FALLBACK_TO_DATASET = os.getenv('TOROB_FALLBACK_TO_DATASET','true').lower() == 'true'
TOROB_LIVE_PRODUCT_LIMIT = min(6,max(1,int(os.getenv('TOROB_LIVE_PRODUCT_LIMIT','3'))))
PUBLISH_PHONE_CONTACTS = os.getenv('PUBLISH_PHONE_CONTACTS','true').lower() == 'true'
PRICE_FRESH_DAYS = max(1, int(os.getenv('PRICE_FRESH_DAYS','7')))
GOOGLE_MAPS_BROWSER_KEY = os.getenv('GOOGLE_MAPS_BROWSER_KEY','').strip()
NESHAN_MAP_KEY = os.getenv('NESHAN_MAP_KEY','').strip()
NESHAN_SERVICE_KEY = os.getenv('NESHAN_SERVICE_KEY','').strip()
SERPER_API_KEY = os.getenv('SERPER_API_KEY','').strip()
GOOGLE_PLACES_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY','').strip()
WEB_RESEARCH_ENABLED = os.getenv('WEB_RESEARCH_ENABLED','true').lower() == 'true'
WEB_PAGE_FETCH_ENABLED = os.getenv('WEB_PAGE_FETCH_ENABLED','true').lower() == 'true'
RESEARCH_TIMEOUT = min(15,max(3,int(os.getenv('RESEARCH_TIMEOUT','10'))))
AGENT_MAX_STEPS = min(10,max(2,int(os.getenv('AGENT_MAX_STEPS','6'))))
AGENT_MAX_TOOLS = min(8,max(1,int(os.getenv('AGENT_MAX_TOOLS','4'))))
AGENT_DEADLINE_SECONDS = min(210,max(30,int(os.getenv('AGENT_DEADLINE_SECONDS','170'))))
AGENT_MODEL_TIMEOUT = min(45,max(3,int(os.getenv('AGENT_MODEL_TIMEOUT','25'))))
AGENT_STATE_TTL = min(3600,max(60,int(os.getenv('AGENT_STATE_TTL','1800'))))
