# Haystack Store Directory

This directory is used for storing Haystack memory persistence files (.pkl) that contain document embeddings for the in-memory implementation of Haystack.

## Purpose

The in-memory Haystack implementation uses this directory to store and retrieve document embeddings between application restarts. This allows the application to maintain vector search capabilities without requiring a running Qdrant instance.

## Files

- `*_documents.pkl`: Pickle files containing serialized Document objects with embeddings
- The actual .pkl files are excluded from git via .gitignore

## Usage

The directory is automatically created and managed by the HaystackMemoryStore class. No manual intervention is required. 