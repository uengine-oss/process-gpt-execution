#!/usr/bin/env python3
"""
Polling Service Main Entry Point

This service handles polling for workitems and processing them.
"""
import os
from dotenv import load_dotenv
from polling_service import run_polling_service

if os.getenv("ENV") != "production":
    load_dotenv()

os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGCHAIN_TAGS"] = "service:polling"

if __name__ == "__main__":
    print("[INFO] Starting Process GPT Polling Service...")
    run_polling_service() 