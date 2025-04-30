# Mobile CSS Architecture

This directory contains the CSS files specifically designed for the mobile version of AskDND. The mobile styling has been refactored to improve maintainability and performance.

## Key Files

- **mobile-style.css**: Main mobile-specific styles including:
  - Mobile layout and structure
  - Mobile header and navigation
  - Mobile chat interface
  - Mobile source panel
  - Mobile buttons and inputs
  - Mobile typography and spacing
  - Dark/light mode support

- **mobile-ios-fixes.css**: iOS-specific fixes including:
  - Safe area inset handling
  - iOS button styling
  - iOS viewport height fixes
  - iOS text input adjustments
  - Safari-specific compatibility fixes

## CSS Architecture

The mobile CSS follows these principles:

1. **Mobile-First Approach**: Styles are designed with mobile as the primary experience
2. **Performance Optimization**: Minimized selectors and efficient CSS rules
3. **Scoped Styling**: Mobile-specific styles use appropriate specificity to avoid conflicts with desktop styles
4. **Responsive Design**: Breakpoints are standardized (Mobile ≤768px, Tablet 769px-950px, Desktop >950px)
5. **Progressive Enhancement**: Core functionality works without advanced CSS, enhanced with modern properties

## Deprecated Files

The old approach (`../mobile.css` in the parent directory) is now deprecated but maintained for backward compatibility. The file includes prominent comments warning about its deprecated status and directing developers to use the new files.

## Media Queries

Mobile-specific media queries are centralized and standardized:

```css
/* Primary mobile breakpoint */
@media (max-width: 768px) {
  /* Mobile styles */
}

/* Tablet breakpoint */
@media (min-width: 769px) and (max-width: 950px) {
  /* Tablet styles */
}
```

## Theme Support

The mobile CSS maintains support for both light and dark themes using CSS variables defined in the main `style.css` file:

```css
/* Using theme variables */
.mobile-element {
  background-color: var(--primary-color);
  color: var(--text-color);
  border: 1px solid var(--border-color);
}
``` 