web: gunicorn --config gunicorn.conf.py app:app
worker: python -c "import app; app.cleanup_old_files()"
