#!/bin/bash

echo "Pull git repo"
git pull

echo "Rebuild and restart container"
sudo docker-compose down && sudo docker-compose build && sudo docker-compose up -d