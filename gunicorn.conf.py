# Gunicorn configuration file
import os

# Server socket
bind = f"0.0.0.0:{os.environ.get('PORT', 5000)}"
backlog = 2048

# Worker processes
workers = 4
worker_class = "sync"
worker_connections = 1000
timeout = 300
keepalive = 30
max_requests = 1000
max_requests_jitter = 100

# Restart workers after this many requests, to help prevent memory leaks
preload_app = True

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'downloader-ninjax'

# Server mechanics
daemon = False
pidfile = '/tmp/gunicorn.pid'
user = None
group = None
tmp_upload_dir = None

# SSL
keyfile = None
certfile = None

# Security
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190
