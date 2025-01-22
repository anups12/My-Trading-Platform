#!/bin/bash

# Pull the latest Docker image from Docker Hub
docker pull my-dockerhub-username/my-django-app:latest

# Run the Docker container
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/mysql-data:/var/lib/mysql \  # Persist MySQL data locally
  --name my-django-app \
  my-dockerhub-username/my-django-app:latest
