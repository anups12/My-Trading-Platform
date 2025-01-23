#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MYSQL_DATA_DIR="$SCRIPT_DIR/mysql-data"

if [ ! -d "$MYSQL_DATA_DIR" ]; then
    echo "Creating MySQL data directory at $MYSQL_DATA_DIR..."
    mkdir -p "$MYSQL_DATA_DIR"
fi

IMAGE_NAME="amanboss/tradingapp:latest"
CONTAINER_NAME="tradingapp"
MYSQL_CONTAINER_NAME="mysql_container"
HOST_PORT=8000

# Pull the latest Docker image
docker pull $IMAGE_NAME

# Stop and remove existing containers
for CONTAINER in $CONTAINER_NAME $MYSQL_CONTAINER_NAME; do
    if [ "$(docker ps -q -f name=$CONTAINER)" ]; then
        echo "Stopping and removing container '$CONTAINER'..."
        docker stop $CONTAINER
        docker rm $CONTAINER
    elif [ "$(docker ps -aq -f name=$CONTAINER)" ]; then
        echo "Removing container '$CONTAINER'..."
        docker rm $CONTAINER
    fi
done

# Start MySQL container
docker run -d \
  --name $MYSQL_CONTAINER_NAME \
  -e MYSQL_ROOT_PASSWORD=rootpassword \
  -e MYSQL_DATABASE=your_db_name \
  -e MYSQL_USER=your_db_user \
  -e MYSQL_PASSWORD=your_db_password \
  -v $MYSQL_DATA_DIR:/var/lib/mysql \
  mysql:latest

# Start Django container
docker run -d \
  -p $HOST_PORT:8000 \
  --env-file $SCRIPT_DIR/.env \
  --name $CONTAINER_NAME \
  $IMAGE_NAME

echo "Containers are running:"
docker ps

echo "Visit the app at http://localhost:$HOST_PORT"
