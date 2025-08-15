#!/usr/bin/env bash
set -e

# Build script for Sinful Delights Shared Lambda Layer
# This creates a Lambda Layer package containing shared Python modules and dependencies

echo "Building Sinful Delights Shared Lambda Layer..."

SHARED_DIR="sinful-delights/shared"
BUILD_DIR="sinful-delights/layer-build"
LAYER_ZIP="sinful-delights/shared-layer.zip"

# Ensure the shared directory exists
if [ ! -d "$SHARED_DIR" ]; then
  echo "Error: Shared directory '$SHARED_DIR' not found."
  exit 1
fi

# Clean any old artifacts
echo "Cleaning previous build artifacts..."
rm -rf "$BUILD_DIR"
rm -f "$LAYER_ZIP"

# Create layer directory structure
# Lambda layers for Python must follow this structure:
# python/lib/python3.x/site-packages/
mkdir -p "$BUILD_DIR/python/lib/python3.11/site-packages"

echo "Installing Python dependencies..."

# Install shared dependencies into the layer
pip install \
  --upgrade \
  --target "$BUILD_DIR/python/lib/python3.11/site-packages" \
  --requirement "$SHARED_DIR/requirements.txt" \
  --no-cache-dir \
  --quiet

echo "Copying shared modules..."

# Copy the shared modules to the layer
# This allows imports like: from shared.models import MenuItem
cp -r "$SHARED_DIR"/* "$BUILD_DIR/python/lib/python3.11/site-packages/"

# Remove unnecessary files to reduce layer size
echo "Optimizing layer size..."
find "$BUILD_DIR" -type f -name "*.pyc" -delete
find "$BUILD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# Remove test files and documentation
find "$BUILD_DIR" -type f -name "test_*.py" -delete
find "$BUILD_DIR" -type f -name "*_test.py" -delete
find "$BUILD_DIR" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type f -name "README*" -delete
find "$BUILD_DIR" -type f -name "CHANGELOG*" -delete
find "$BUILD_DIR" -type f -name "LICENSE*" -delete

echo "Creating layer package..."

# Create the zip package from the build directory
cd "$BUILD_DIR"
zip -r "../shared-layer.zip" . > /dev/null

cd - > /dev/null

# Display layer contents for verification
echo "Layer package contents:"
unzip -l "$LAYER_ZIP" | head -20
echo "..."
unzip -l "$LAYER_ZIP" | tail -5

# Display layer size
LAYER_SIZE=$(du -h "$LAYER_ZIP" | cut -f1)
echo "Layer package size: $LAYER_SIZE"

# Verify the layer structure
echo "Verifying layer structure..."
if unzip -l "$LAYER_ZIP" | grep -q "python/lib/python3.11/site-packages/shared/"; then
  echo "✓ Shared modules found in correct location"
else
  echo "✗ Shared modules not found in expected location"
  exit 1
fi

if unzip -l "$LAYER_ZIP" | grep -q "python/lib/python3.11/site-packages/pydantic/"; then
  echo "✓ Pydantic dependency found"
else
  echo "✗ Pydantic dependency not found"
fi

if unzip -l "$LAYER_ZIP" | grep -q "python/lib/python3.11/site-packages/boto3/"; then
  echo "✓ Boto3 dependency found"
else
  echo "✗ Boto3 dependency not found"
fi

# Check layer size (AWS limit is 50MB compressed, 250MB uncompressed)
LAYER_SIZE_BYTES=$(stat -f%z "$LAYER_ZIP" 2>/dev/null || stat -c%s "$LAYER_ZIP")
LAYER_SIZE_MB=$((LAYER_SIZE_BYTES / 1024 / 1024))

if [ $LAYER_SIZE_MB -gt 50 ]; then
  echo "⚠️  Warning: Layer size ($LAYER_SIZE_MB MB) exceeds AWS 50MB limit"
  echo "   Consider removing unnecessary dependencies or splitting into multiple layers"
else
  echo "✓ Layer size ($LAYER_SIZE_MB MB) is within AWS limits"
fi

echo "✓ Shared Lambda Layer build complete!"
echo "   Package: $LAYER_ZIP"
echo "   Ready for deployment to AWS Lambda"

# Clean up build directory
rm -rf "$BUILD_DIR"