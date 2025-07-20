# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Codebase Architecture

This is a multi-project lambda function repository containing several independent lambda projects:
- CMC (Movie/Voting related lambdas)
- Landholders Law
- OWE (Service Requests)
- Sinful Delights
- Stricklin (Event Management)

Each project follows a similar structure:
- `*-lambda/` directories contain individual AWS Lambda functions
- `app.py` is the main lambda handler for each function
- `requirements.txt` defines Python dependencies (primarily boto3)

## Development Commands

### Deployment
- Deployment is automated via GitHub Actions in `.github/workflows/deploy-lambdas.yml`
- Lambdas are built and deployed only if their specific folder has changed
- Deployment script: `build-lambda.sh`

### Lambda Deployment Workflow
1. GitHub Action discovers lambda folders
2. Checks if specific lambda folder has changes
3. Builds lambda function (creates lambda.zip)
4. Deploys to AWS Lambda with function name: `{project}-{lambda-folder}`

### Local Development Considerations
- Each lambda is a standalone Python project
- Use `requirements.txt` to manage dependencies
- Use a virtual environment for local development
- Recommended: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`

## AWS and Credentials
- AWS credentials managed via GitHub Secrets
- Region: us-east-1
- Credentials required: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

## Testing
- No standard testing framework detected
- Recommend adding unit tests for each lambda function
- Test events can be found in `test_event.json` files

## Key Dependencies
- Primary dependency: boto3 (AWS SDK for Python)
- Versions pinned in each lambda's requirements.txt