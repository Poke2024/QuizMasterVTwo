import os
from datetime import timedelta

# Flask configuration
DEBUG = True
SECRET_KEY = os.environ.get("SESSION_SECRET", "dev-secret-key")
SQLALCHEMY_DATABASE_URI = "sqlite:///quiz_master.db"
SQLALCHEMY_TRACK_MODIFICATIONS = False

# JWT configuration
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "jwt-secret-key")
JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

# Redis configuration
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Celery configuration
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'

# Email configuration
MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
MAIL_USE_TLS = True
MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "youremail@gmail.com")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "yourpassword")
MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@quizmaster.com")

# Admin account
ADMIN_USERNAME = "admin@quizmaster.com"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# Application configuration
APP_URL = os.environ.get("APP_URL", "http://localhost:5000")

# Cache configuration
CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes cache timeout
CACHE_TYPE = "RedisCache"
