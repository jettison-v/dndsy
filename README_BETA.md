# Beta Framework for DnDSy

This branch implements a development environment separation for DnDSy, allowing developers to work without affecting the production environment.

## Features

1. **Environment Separation**: All development happens in isolated collections and S3 bucket
2. **Vector Store Prefixing**: Development vector stores are prefixed with `dev__`
3. **S3 Infrastructure Duplication**: Uses a separate `dev-askdnd-ai` S3 bucket
4. **Environment Detection**: Automatically detects and applies the correct environment settings
5. **Responsive Mobile UI**: Fully optimized mobile interface with consistent breakpoints

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

## Mobile UI Enhancements

The Beta version includes significant improvements to the mobile user experience:

1. **Standardized Breakpoints**: 
   - Mobile: Devices up to 768px width
   - Tablet: Devices 769px-950px width
   - Desktop: Devices above 950px width

2. **Device-Specific Source Panel Behavior**:
   - Mobile: Full-screen source panel with optimized navigation
   - Tablet: Full-screen source panel with desktop interface elements
   - Desktop: Side panel with expand/collapse functionality

3. **Responsive Styling**:
   - Consistent source panel appearance and behavior across all devices
   - Mobile-optimized controls for zooming and navigation
   - Improved touch interaction for small screens

4. **Architectural Components**:
   - `mobile.css`: Dedicated styles for mobile devices
   - `mobile-ui.js`: Handles mobile-specific interactions
   - `source_panel.js`: Manages panel behavior across all device types

## Deployment

When deploying, make sure to set the correct environment variable:
- For production deployment: `ENV=production` or leave unset
- For development/staging deployment: `ENV=development` 