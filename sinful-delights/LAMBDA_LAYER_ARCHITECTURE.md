# 🏗️ Sinful Delights Lambda Layer Architecture

This document explains the Lambda Layer architecture implemented for the Sinful Delights API to enable efficient code reuse and dependency management across all Lambda functions.

## 📋 Overview

The Sinful Delights project uses AWS Lambda Layers to share common code and dependencies across multiple Lambda functions, reducing deployment package sizes and improving maintainability.

### Architecture Components

```
sinful-delights/
├── shared/                           # Shared layer source code
│   ├── models.py                     # Pydantic models (OpenAPI schemas)
│   ├── auth.py                       # Authentication utilities  
│   ├── dynamo.py                     # DynamoDB helpers
│   ├── errors.py                     # Error handling utilities
│   ├── s3.py                         # S3 utilities
│   ├── utils.py                      # General utilities
│   └── requirements.txt              # Layer dependencies
├── *-lambda/                         # Individual Lambda functions
│   ├── app.py                        # Function handler
│   ├── requirements.txt              # Original requirements (for reference)
│   └── requirements-lambda.txt       # Function-specific requirements (minimal)
└── .layer-version                    # Current deployed layer version
```

## 🚀 Deployment Process

### 1. Shared Layer Deployment
The shared layer is deployed automatically when changes are detected in the `shared/` directory:

```yaml
# .github/workflows/deploy-shared-layer.yml
on:
  push:
    paths:
      - 'sinful-delights/shared/**'
```

**Process:**
1. **Build**: `build-shared-layer.sh` creates optimized layer package
2. **Deploy**: AWS Lambda Layer is published with new version
3. **Update**: Layer version is committed back to repository
4. **Optimize**: Removes unnecessary files (~test files, docs, cache)

### 2. Lambda Function Deployment  
Lambda functions are built using the enhanced build script:

```bash
./build-lambda-with-layer.sh sinful-delights/get-menu-today-lambda
```

**Process:**
1. **Dependencies**: Only installs function-specific requirements (not shared ones)
2. **Package**: Creates minimal deployment package
3. **Layer**: Function is configured to use the shared layer at runtime
4. **Environment**: Sets `PYTHONPATH=/opt/python` for layer imports

## 📦 Layer Contents

### Shared Dependencies
- **boto3** ~1.28 (AWS SDK)
- **pydantic** ~2.0 (Data validation)
- **python-jose** ~3.3 (JWT handling)
- **requests** ~2.31 (HTTP client)

### Shared Modules
- **shared.models**: OpenAPI-compliant Pydantic models
- **shared.auth**: Customer/admin authentication utilities
- **shared.dynamo**: DynamoDB operations with atomic transactions
- **shared.errors**: Standardized error handling
- **shared.s3**: S3 presigned URL generation
- **shared.utils**: Date validation, pagination, sanitization

## 🔧 Usage in Lambda Functions

### Import Shared Modules
```python
import sys
import os

# Add shared layer to path (handled automatically in AWS)
sys.path.append('/opt/python')

# Import shared utilities
from shared.auth import validate_customer_access, get_user_id
from shared.errors import handle_exceptions, create_success_response
from shared.dynamo import get_item, decrement_stock
from shared.models import MenuItem, Menu, CreateOrderRequest
```

### Function Structure
```python
@handle_exceptions
def lambda_handler(event, context):
    # Validate authentication
    validate_customer_access(event)
    user_id = get_user_id(event)
    
    # Use shared utilities
    result = get_item(f"USER#{user_id}", "DETAILS")
    
    # Return standardized response
    return create_success_response(result)
```

## 📊 Benefits

### ✅ Reduced Package Sizes
- **Before**: Each Lambda ~15-25MB (with boto3, pydantic, etc.)
- **After**: Each Lambda ~1-3MB (function code only)
- **Layer**: ~10-15MB (shared across all functions)

### ✅ Faster Deployments
- Functions deploy faster with smaller packages
- Layer deployed only when shared code changes
- Parallel function deployments possible

### ✅ Better Maintainability
- Single source of truth for shared logic
- Consistent error handling across all endpoints  
- Centralized model definitions
- Easier testing and validation

### ✅ Cost Optimization
- Reduced storage costs (smaller packages)
- Faster cold starts (smaller downloads)
- Improved Lambda performance

## ⚙️ Configuration

### Layer ARN Format
```
arn:aws:lambda:us-east-1:{ACCOUNT_ID}:layer:sinful-delights-shared-layer:{VERSION}
```

### Environment Variables
Functions using the layer automatically receive:
```bash
PYTHONPATH=/opt/python  # Enables layer imports
```

### Function Configuration
```bash
# AWS CLI example
aws lambda update-function-configuration \
  --function-name "sinful-delights-get-menu-today-lambda" \
  --layers "arn:aws:lambda:us-east-1:123456789012:layer:sinful-delights-shared-layer:5"
```

## 🔄 Development Workflow

### Adding New Shared Functionality
1. **Update** shared modules in `sinful-delights/shared/`
2. **Test** locally using the shared modules
3. **Commit** changes to trigger layer deployment
4. **Deploy** functions will automatically use new layer version

### Adding New Lambda Function
1. **Create** function directory: `sinful-delights/new-function-lambda/`
2. **Add** `app.py` with function logic
3. **Create** `requirements-lambda.txt` (usually empty for sinful-delights)
4. **Import** shared modules as needed
5. **Commit** to trigger function deployment with layer

### Local Development
```bash
# Set up local environment
export PYTHONPATH="sinful-delights/shared:$PYTHONPATH"

# Run local tests
python -m pytest sinful-delights/tests/

# Build and test layer locally
./build-shared-layer.sh
```

## 📈 Monitoring & Troubleshooting

### Layer Version Tracking
Check current layer version:
```bash
cat sinful-delights/.layer-version
# SINFUL_DELIGHTS_SHARED_LAYER_VERSION=12
```

### Function Configuration
Verify layer attachment:
```bash
aws lambda get-function-configuration \
  --function-name "sinful-delights-get-menu-today-lambda" \
  --query 'Layers[].Arn'
```

### Common Issues

**Import Errors**: Ensure `PYTHONPATH=/opt/python` is set
**Version Conflicts**: Check layer version matches expectations  
**Package Size**: Ensure function doesn't duplicate layer dependencies

### Logs and Debugging
```python
# Add to function for debugging
import sys
print(f"Python path: {sys.path}")
print(f"Available modules: {os.listdir('/opt/python')}")
```

## 🔮 Future Enhancements

- **Multiple Layers**: Separate common AWS dependencies from business logic
- **Versioning**: Semantic versioning for layer releases
- **Testing**: Automated layer testing before deployment
- **Monitoring**: Layer usage analytics and performance metrics
- **Cross-Project**: Extend layer architecture to other projects

---

**Last Updated**: August 15, 2025  
**Layer Version**: Auto-updated by GitHub Actions  
**Compatibility**: Python 3.9, 3.10, 3.11