# Base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Pass secrets as build args
ARG DJANGO_SECRET_KEY
ARG DATABASE_NAME
ARG DATABASE_USER
ARG DATABASE_PASSWORD

# Set environment variables for Django
ENV DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY
ENV DATABASE_NAME=$DATABASE_NAME
ENV DATABASE_USER=$DATABASE_USER
ENV DATABASE_PASSWORD=$DATABASE_PASSWORD

# Copy compiled Cython files
COPY *.so /app/
COPY manage.py /app/

# Expose Django's default port
EXPOSE 8000

# Run Django server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
