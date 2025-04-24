# Beta Framework for DnDSy

This branch implements a development environment separation for DnDSy, allowing developers to work without affecting the production environment.

## Features

1. **Environment Separation**: All development happens in isolated collections and S3 bucket
2. **Vector Store Prefixing**: Development vector stores are prefixed with `dev__`
3. **S3 Infrastructure Duplication**: Uses a separate `dev-askdnd-ai` S3 bucket
4. **Environment Detection**: Automatically detects and applies the correct environment settings

## How to Use

### Setup

1. Check out the beta-framework branch:
   ```bash
   git checkout beta-framework
   ```

2. Set up your environment:
   ```bash
   # Create a .env file with development settings
   echo "ENV=development" > .env
   ```

3. Run the application:
   ```bash
   # Standard development startup
   flask run
   ```

### Data Processing

Process PDFs into the development vector stores:

```bash
python -m scripts.manage_vector_stores --cache-behavior rebuild
```

### API Endpoints

The new `/api/admin/system-info` endpoint provides information about the current environment, vector stores, and S3 configuration.

## Environment Detection

The system detects the environment through the `ENV` environment variable:
- `ENV=development` or `ENV=dev` or `ENV=beta` - Use development environment
- Any other value (or unset) - Use production environment

## Implementation Details

### Environment-Specific Prefixes

Vector store collections in development mode are prefixed with `dev__`, for example:
- Production: `dnd_semantic`
- Development: `dev__dnd_semantic`

### S3 Bucket Naming

The S3 bucket for development is prefixed with `dev-`, for example:
- Production: `askdnd-ai`
- Development: `dev-askdnd-ai`

## Deployment

When deploying, make sure to set the correct environment variable:
- For production deployment: `ENV=production` or leave unset
- For development/staging deployment: `ENV=development` 