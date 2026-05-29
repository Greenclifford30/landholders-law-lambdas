#!/usr/bin/env bash
set -e

# Enhanced Lambda build script that works with shared Lambda Layer
# Usage: ./build-lambda-with-layer.sh <folder-name>
# Example: ./build-lambda-with-layer.sh sinful-delights/get-menu-today-lambda

if [ -z "$1" ]; then
  echo "Usage: $0 <lambda-folder>"
  exit 1
fi

LAMBDA_FOLDER="$1"

# Ensure the folder exists
if [ ! -d "$LAMBDA_FOLDER" ]; then
  echo "Error: directory '$LAMBDA_FOLDER' not found."
  exit 1
fi

echo "Building Lambda function: $LAMBDA_FOLDER"

# Extract project name and lambda name
PROJECT=$(echo "$LAMBDA_FOLDER" | cut -d'/' -f1)
LAMBDA_NAME=$(echo "$LAMBDA_FOLDER" | cut -d'/' -f2)

echo "Project: $PROJECT, Lambda: $LAMBDA_NAME"

# Navigate to lambda folder
cd "$LAMBDA_FOLDER"

# Clean any old artifacts
rm -rf build
mkdir build

# Check if this is a sinful-delights lambda (uses shared layer)
if [ "$PROJECT" = "sinful-delights" ]; then
  echo "Using shared layer approach for sinful-delights project..."
  
  # Install only lambda-specific dependencies (excluding shared dependencies)
  if [ -f "requirements-lambda.txt" ]; then
    echo "Installing lambda-specific dependencies from requirements-lambda.txt..."
    pip install --upgrade -r requirements-lambda.txt -t build --quiet
  else
    echo "No requirements-lambda.txt found, checking requirements.txt..."
    if [ -f "requirements.txt" ]; then
      # Filter out shared dependencies to avoid duplication
      echo "Filtering shared dependencies from requirements.txt..."
      grep -v -E "^(boto3|pydantic|python-jose|requests)" requirements.txt > requirements-filtered.txt || true
      
      if [ -s requirements-filtered.txt ]; then
        echo "Installing filtered dependencies..."
        pip install --upgrade -r requirements-filtered.txt -t build --quiet
      else
        echo "No additional dependencies needed (all provided by shared layer)"
      fi
      
      rm -f requirements-filtered.txt
    fi
  fi
else
  echo "Using traditional approach for non-sinful-delights project..."
  
  # Install all dependencies (traditional approach)
  if [ -f "requirements.txt" ]; then
    pip install --upgrade -r requirements.txt -t build --quiet
  fi
fi

# Copy source code into build folder
echo "Copying source code..."
cp *.py build/ 2>/dev/null || echo "No Python files to copy"

# Copy any additional files if they exist
[ -f "*.json" ] && cp *.json build/ 2>/dev/null || true

# Create the zip package
echo "Creating deployment package..."
cd build
zip -r ../lambda.zip . > /dev/null

cd ..

# Display package info
PACKAGE_SIZE=$(du -h lambda.zip | cut -f1)
echo "✓ Lambda build complete!"
echo "  Package: $LAMBDA_FOLDER/lambda.zip"
echo "  Size: $PACKAGE_SIZE"

if [ "$PROJECT" = "sinful-delights" ]; then
  echo "  Note: This function will use the sinful-delights-shared-layer at runtime"
fi