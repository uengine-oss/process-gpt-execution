#!/usr/bin/env python3
"""
FCM Service Main Entry Point

This service handles Firebase Cloud Messaging (FCM) push notifications.
"""
import os
from dotenv import load_dotenv
from fcm_service import run_fcm_service

if os.getenv("ENV") != "production":
    load_dotenv()

if __name__ == "__main__":
    print("[INFO] Starting FCM Service...")
    run_fcm_service()