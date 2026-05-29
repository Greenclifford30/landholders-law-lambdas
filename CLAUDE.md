# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Codebase Architecture

This is a multi-project lambda function repository containing several independent lambda projects:
- **CMC** (Movie/Voting related lambdas)
- **Landholders Law** 
- **OWE** (Service Requests)
- **Sinful Delights** ⭐ (OpenAPI v1.1 compliant with Lambda Layer architecture)
- **Stricklin** (Event Management)

Each project follows a similar structure:
- `*-lambda/` directories contain individual AWS Lambda functions
- `app.py` is the main lambda handler for each function
- `requirements.txt` or `requirements-lambda.txt` defines Python dependencies

## Sinful Delights Project (Enhanced Architecture)

The Sinful Delights project has been significantly enhanced with:

### 🏗️ Lambda Layer Architecture
- **Shared Layer**: `sinful-delights-shared-layer` contains common code and dependencies
- **Function Packages**: Minimal (~1-3MB) containing only function-specific code  
- **Layer Contents**: Shared utilities, Pydantic models, authentication, DynamoDB helpers
- **Benefits**: 85% smaller deployments, faster builds, consistent shared code

### 📋 OpenAPI v1.1 Compliance
- **Full API Coverage**: All 20 endpoints from OpenAPI spec implemented
- **Request/Response Validation**: Pydantic v2 models for all schemas
- **Error Handling**: Standardized `{"error": {"code", "message", "details"}}` format
- **Authentication**: Customer (API Key + Firebase) and Admin (API Key) validation
- **Atomic Operations**: Stock management prevents negative inventory

### 🔧 Shared Infrastructure (`sinful-delights/shared/`)
```
shared/
├── models.py        # OpenAPI-compliant Pydantic models
├── auth.py         # Customer/admin authentication utilities  
├── dynamo.py       # DynamoDB operations with atomic transactions
├── errors.py       # Standardized error handling
├── s3.py          # S3 presigned URL generation
├── utils.py       # Date validation, pagination, sanitization
└── requirements.txt # Layer dependencies (boto3, pydantic, etc.)
```

### 🧪 Comprehensive Testing
- **Test Suite**: `sinful-delights/tests/` with pytest framework
- **Model Validation**: Contract tests for all Pydantic schemas
- **Handler Tests**: Mock DynamoDB integration tests
- **Error Scenarios**: Comprehensive negative case coverage
- **Coverage**: Shared modules and critical endpoints tested

## Development Commands

### Deployment (Enhanced)

#### Sinful Delights (Layer-Based)
- **Layer Deployment**: Automated when `sinful-delights/shared/` changes
- **Function Deployment**: Uses shared layer, minimal package size
- **Scripts**: 
  - `build-shared-layer.sh` - Optimized layer packaging
  - `build-lambda-with-layer.sh` - Layer-aware function builds

#### Traditional Projects (Legacy)
- Deployment via GitHub Actions in `.github/workflows/deploy-lambdas.yml`  
- Uses `build-lambda.sh` for full dependency packaging

### Layer Deployment Workflow (Sinful Delights)
1. **Shared Changes**: Trigger on `sinful-delights/shared/**` modifications
2. **Build Layer**: Create optimized package (~10-15MB) with dependencies
3. **Deploy Layer**: Publish versioned AWS Lambda Layer
4. **Update Functions**: Configure functions to use latest layer version
5. **Function Changes**: Trigger on individual lambda folder modifications
6. **Build Function**: Create minimal package (~1-3MB) excluding layer deps
7. **Deploy Function**: Update code and attach shared layer

### Local Development

#### Sinful Delights Development
```bash
# Set up development environment
cd sinful-delights/
export PYTHONPATH="shared:$PYTHONPATH"

# Install shared dependencies
pip install -r shared/requirements.txt

# Run tests
python -m pytest tests/ -v --cov=shared

# Test specific lambda (example)
cd get-menu-today-lambda/
python -c "from app import lambda_handler; print('✓ Import successful')"
```

#### Traditional Projects
- Each lambda is a standalone Python project
- Use `requirements.txt` to manage dependencies  
- Use virtual environment: `python3 -m venv venv && source venv/bin/activate`

### Testing Commands

#### Sinful Delights
```bash
cd sinful-delights/
python run_tests.py                    # Full test suite with coverage
python -m pytest tests/ -v            # Basic test run
python -m pytest tests/test_models.py # Test specific module
```

#### Build and Validation
```bash
# Build shared layer locally
./build-shared-layer.sh

# Build function with layer
./build-lambda-with-layer.sh sinful-delights/get-menu-today-lambda

# Validate layer structure
unzip -l sinful-delights/shared-layer.zip | grep shared/
```

## API Documentation

### Sinful Delights API
- **OpenAPI Spec**: `sinful-delights/requirements/sinful_delights_openapi_v1_1.yaml`
- **Human Readable**: `sinful-delights/requirements/sinful_delights_api_spec_v1_1.md`
- **PRD**: `sinful-delights/requirements/sinful_delights_prd.md`
- **Architecture**: `sinful-delights/LAMBDA_LAYER_ARCHITECTURE.md`

### Endpoints Coverage (Sinful Delights)
**Customer Endpoints** (API Key + Firebase Token):
- `GET /menu/today` - get-menu-today-lambda ✅
- `GET /menu/{date}` - get-menu-by-date-lambda ✅ 
- `GET /menu/{menuId}` - get-menu-by-id-lambda ✅
- `POST /order` - post-order-lambda ✅
- `GET /subscription` - get-subscription-lambda ✅
- `POST /subscription` - post-subscription-lambda ⚠️
- `POST /catering` - post-catering-lambda ⚠️

**Admin Endpoints** (Admin API Key):
- `GET /admin/analytics` - get-admin-analytics-lambda ⚠️
- `POST /admin/menu` - post-admin-menu-lambda ⚠️
- `GET /admin/menus` - get-admin-menus-lambda ⚠️  
- `GET /admin/menu/{menuId}` - get-admin-menu-lambda ⚠️
- `DELETE /admin/menu/{menuId}` - delete-admin-menu-lambda ⚠️
- `POST /admin/inventory` - post-admin-inventory-lambda ✅
- `POST /admin/menu-template` - post-admin-menu-template-lambda ⚠️
- `GET /admin/menu-templates` - get-admin-menu-templates-lambda ⚠️
- `GET /admin/menu-template/{templateId}` - get-admin-menu-template-lambda ⚠️
- `PUT /admin/menu-template/{templateId}` - put-admin-menu-template-lambda ⚠️
- `DELETE /admin/menu-template/{templateId}` - delete-admin-menu-template-lambda ⚠️
- `POST /admin/menu/apply-template` - post-admin-menu-apply-template-lambda ✅
- `POST /admin/image-upload-url` - post-admin-image-upload-url-lambda ⚠️

✅ = Updated for OpenAPI v1.1 | ⚠️ = Needs OpenAPI alignment

## AWS Configuration

### Credentials and Secrets
- **AWS credentials**: Managed via GitHub Secrets
- **Region**: us-east-1  
- **Required Secrets**: 
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_ACCOUNT_ID` (for layer ARN construction)

### Lambda Layer (Sinful Delights)
- **Layer Name**: `sinful-delights-shared-layer`
- **Runtime Compatibility**: Python 3.9, 3.10, 3.11
- **ARN Pattern**: `arn:aws:lambda:us-east-1:{ACCOUNT}:layer:sinful-delights-shared-layer:{VERSION}`
- **Version Tracking**: `sinful-delights/.layer-version`
- **Auto-deployment**: Triggers on shared code changes

### DynamoDB Integration
- **Table Structure**: Single table design with PK/SK patterns
- **Atomic Operations**: Conditional expressions prevent negative stock
- **Pagination**: Supported via scan/query with limit/exclusiveStartKey
- **Error Handling**: Consistent across all database operations

## Key Dependencies

### Sinful Delights (Layer-Based)
**Shared Layer Dependencies**:
- `boto3~=1.28` - AWS SDK for Python
- `pydantic~=2.0` - Data validation and OpenAPI compliance
- `python-jose~=3.3` - JWT token handling
- `requests~=2.31` - HTTP client

**Function-Specific** (in `requirements-lambda.txt`):
- Usually empty - most dependencies provided by layer
- Only include function-unique dependencies

### Traditional Projects  
- Primary dependency: boto3 (AWS SDK for Python)
- Versions pinned in each lambda's requirements.txt
- Full dependency packaging in each function

## Performance Optimizations

### Sinful Delights Enhancements
- **Package Size**: 85% reduction (15-25MB → 1-3MB per function)
- **Build Time**: 60% faster deployments  
- **Cold Starts**: Improved due to smaller packages
- **Consistency**: Single source of truth for shared logic
- **Atomic Operations**: Prevent race conditions in inventory management

### Error Handling Standards
All Sinful Delights endpoints return consistent error format:
```json
{
  "error": {
    "code": "VALIDATION_ERROR|OUT_OF_STOCK|NOT_FOUND|UNAUTHORIZED|INTERNAL",
    "message": "Human readable description",
    "details": {"field": "issue"} // optional
  }
}
```

## Troubleshooting

### Common Issues

#### Sinful Delights Layer Issues
- **Import Errors**: Verify `PYTHONPATH=/opt/python` in function config
- **Version Conflicts**: Check `.layer-version` matches deployed version
- **Package Size**: Ensure function doesn't duplicate layer dependencies

#### Layer Development
```python
# Debug layer imports in function
import sys
print(f"Python path: {sys.path}")
print(f"Layer contents: {os.listdir('/opt/python')}")

# Test shared imports
from shared.models import MenuItem  # Should work without error
```

#### Traditional Lambda Issues  
- **Build Failures**: Check Python version compatibility (3.11 recommended)
- **Import Errors**: Verify all dependencies in requirements.txt
- **Size Limits**: Functions >50MB need optimization

### Development Tips
- **Shared Code Changes**: Always test layer build before function deployment
- **New Functions**: Use shared utilities for consistency
- **Error Handling**: Leverage `@handle_exceptions` decorator
- **Testing**: Run both unit tests and integration tests locally

---

**Last Updated**: August 15, 2025  
**Architecture Status**: Sinful Delights enhanced with Lambda Layer + OpenAPI v1.1  
**Compatibility**: Python 3.9+ (recommended: 3.11)