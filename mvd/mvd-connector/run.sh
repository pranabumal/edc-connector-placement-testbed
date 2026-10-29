#!/bin/bash

set -e

# Build a JAR-file
../../gradlew clean :mvd:mvd-connector:build

# Run the connectors
java -Dedc.fs.config=../resources/configuration/consumer-config.properties -jar build/libs/connector.jar &
consumer_process_id=$!

java -Dedc.fs.config=../resources/configuration/provider-config.properties -jar build/libs/connector.jar &
provider_process_id=$!

# Create Docker image
#docker build -t mvd:1.5 -f ../Dockerfile .

# Shutdown running connectors
cleanup() {
    echo $'\n'"Shutting down connectors..."
    kill $consumer_process_id 2>/dev/null
    kill $provider_process_id 2>/dev/null
    wait
    echo "Shutdown complete!"
}

trap cleanup EXIT # calls cleanup upon sigint received

wait