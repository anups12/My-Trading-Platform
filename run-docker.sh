#!/bin/bash

# Get the directory of the running script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MYSQL_DATA_DIR="$SCRIPT_DIR/mysql-data"

if [ ! -d "$MYSQL_DATA_DIR" ]; then
    echo "Creating MySQL data directory at $MYSQL_DATA_DIR..."
    mkdir -p "$MYSQL_DATA_DIR"
fi

# Set variables
IMAGE_NAME="amanboss/tradingapp:latest"
CONTAINER_NAME="tradingapp"
HOST_PORT=8000

# Pull the latest Docker image from Docker Hub
echo "Pulling the latest Docker image..."
docker pull $IMAGE_NAME

# Check if the container is already running
if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    echo "Container '$CONTAINER_NAME' is already running. Stopping and removing it..."
    docker stop $CONTAINER_NAME
    docker rm $CONTAINER_NAME
fi

# Check if the container exists (but is not running)
if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
    echo "Removing existing container '$CONTAINER_NAME'..."
    docker rm $CONTAINER_NAME
fi

# Ensure the mysql-data directory exists
if [ ! -d "$MYSQL_DATA_DIR" ]; then
    echo "Creating MySQL data directory at $MYSQL_DATA_DIR..."
    mkdir -p $MYSQL_DATA_DIR
fi

# Run the Docker container
echo "Starting the Docker container..."
docker run -d \
  -p $HOST_PORT:8000 \
  -v $MYSQL_DATA_DIR:/var/lib/mysql \
  --name $CONTAINER_NAME \
  $IMAGE_NAME

# Provide feedback to the user
echo "Container '$CONTAINER_NAME' is up and running."
echo "Visit the app at http://localhost:$HOST_PORT"
