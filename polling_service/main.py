#!/usr/bin/env python3
"""
Polling Service Main Entry Point

This service handles polling for workitems and processing them.
"""
from polling_service import run_polling_service

if __name__ == "__main__":
    print("[INFO] Starting Process GPT Polling Service...")
    run_polling_service() 