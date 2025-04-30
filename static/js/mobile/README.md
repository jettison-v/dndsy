# Mobile Implementation Architecture

This directory contains the JavaScript files for the mobile-specific implementation of AskDND. The mobile experience has been refactored to use a modular architecture with shared utilities.

## Key Files

- **mobile-core.js**: Core mobile functionality including:
  - Mobile UI initialization
  - Settings panel toggle functionality
  - Source panel basic behavior
  - Touch event handling
  - Global mobile UI state management

- **mobile-chat.js**: Mobile chat interactions including:
  - Chat message handling
  - User input management
  - Response streaming
  - Source pill generation and interaction
  - Markdown formatting (via dnd-utilities.js)
  - Event handlers for mobile-specific interactions

- **mobile-source-panel.js**: Mobile source panel management including:
  - Source content fetching and display
  - Source navigation between pages
  - Zoom controls for image content
  - Mobile-optimized panel behavior

## Shared Utilities

The mobile implementation uses shared utilities from `../dnd-utilities.js`, which centralizes common functionality used by both desktop and mobile experiences:

- Markdown formatting
- Link processing
- Source content fetching
- Text processing utilities

## Architecture Notes

1. **Separation of Concerns**: Each file handles a specific aspect of the mobile experience to maintain code clarity.

2. **Event Delegation**: Event handlers are centralized and use event delegation where possible to improve performance.

3. **Progressive Enhancement**: The mobile experience builds on core functionality with mobile-specific optimizations.

4. **Responsive Design**: The UI adapts to different mobile screen sizes while maintaining a consistent user experience.

5. **Deprecated Files**: The old approach (`mobile-ui.js` and `mobile.css` in the parent directories) is now deprecated but maintained for backward compatibility.

## Mobile-Specific HTML

The mobile HTML templates are located in `/templates/mobile/` and include:

- **mobile-base.html**: Base template with common head elements and mobile meta tags
- **mobile-index.html**: Main mobile chat interface
- **mobile-login.html**: Mobile-optimized login page

## Mobile-Specific CSS

The mobile CSS files are located in `/static/css/mobile/` and include:

- **mobile-style.css**: Main mobile styles
- **mobile-ios-fixes.css**: iOS-specific fixes for proper display on iOS devices 