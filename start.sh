#!/bin/bash

# Exit on any error
set -e

echo "Starting Django application..."

# Change to the src directory where manage.py is located
cd /app/src

# Create logs directory if it doesn't exist
mkdir -p logs

# Run database migrations
echo "Running database migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start the application
echo "Starting Daphne server..."
exec daphne -b 0.0.0.0 -p ${PORT:-8000} core.asgi:application 