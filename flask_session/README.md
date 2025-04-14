# Flask Session Directory

This directory is used for storing Flask session files that maintain user session data between requests.

## Purpose

Flask uses filesystem-based session storage to persist user session information across requests. This directory stores these session files.

## Files

- Session files are binary files with randomized names
- All files in this directory are excluded from git via .gitignore

## Usage

The directory is automatically managed by Flask-Session. No manual intervention is required. 