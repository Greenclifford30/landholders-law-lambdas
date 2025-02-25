#!/usr/bin/env bash
set -e

# Usage: ./build-lambda.sh <folder-name>
# Example: ./build-lambda.sh consultation

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

# 1) Navigate to that folder
cd "$LAMBDA_FOLDER"

# 2) Clean any old artifacts
rm -rf build
mkdir build

# 3) Install dependencies into 'build' directory
pip install --upgrade -r requirements.txt -t build

# 4) Copy source code into 'build' folder
cp app.py build/

# 5) Create the zip package
cd build
zip -r ../lambda.zip .  > /dev/null

cd ..
echo "Lambda build complete! Package created: $LAMBDA_FOLDER/lambda.zip"
