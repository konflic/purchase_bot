#!/bin/bash

echo "Pull git repo"
git pull

echo "Rebuild and restart container"
docker-compose down && docker-compose build && docker-compose up -d

echo "Delete old images"
docker rmi $(docker images -q)

echo "Current state"
docker ps