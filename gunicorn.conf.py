"""Keep health checks responsive while a supplier request is waiting on I/O."""
worker_class = "gthread"
workers = 1
threads = 4
timeout = 60
graceful_timeout = 60
