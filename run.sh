#!/bin/bash

set -e

# Build the Docker image
echo "Building Docker image..."
docker build -t assertion-extractor .

rm -rf /tmp/test_extractor

mkdir -p output

# Repositories
repositories=(
    "https://github.com/pytest-dev/pytest.git"
    "https://github.com/django/django.git"
    "https://github.com/pallets/flask.git"
)

# Run extraction for each repository inside Docker
for repo in "${repositories[@]}"; do
    repo_name=$(basename "$repo" .git)
    output_file="output/${repo_name}_assertions.csv"

    echo "Processing $repo_name..."

    if docker run --rm -v "$(pwd)/output:/output" assertion-extractor "$repo" "/output/${repo_name}_assertions.csv"; then
        if [[ -f "$output_file" ]]; then
            echo "Results saved to $output_file"
        else
            echo "Failed to process $repo_name"
        fi
    else
        echo -e "Error processing $repo_name"
        [[ -f "$output_file" ]] && rm "$output_file"
    fi
done

echo "All repositories processed."
