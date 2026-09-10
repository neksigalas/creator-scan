"""
Vercel serverless entry point for CreatorScan.
Imports the FastAPI app from app.py and exposes it as 'app'.
"""
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: F401 — Vercel picks up 'app' automatically
