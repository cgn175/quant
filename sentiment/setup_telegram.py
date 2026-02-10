#!/usr/bin/env python3
"""
Setup script for Telegram authentication.

This script helps you set up Telegram authentication for the sentiment fetcher.
It creates a session file that will be used for future API calls.

Usage:
    python setup_telegram.py

You'll need:
1. Telegram API ID and API Hash from https://my.telegram.org/apps
2. Your phone number registered with Telegram
3. Access to your Telegram account to receive verification code

Security:
- Session files are stored locally with restricted permissions (0600)
- Never commit session files to git (they're in .gitignore)
- API credentials should be in environment variables or .env file
"""

import asyncio
import os
import sys
from getpass import getpass

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

# Load environment variables from .env file
load_dotenv()


async def setup_telegram_session():
    """Interactive setup for Telegram session."""
    
    print("=" * 60)
    print("Telegram Sentiment Fetcher Setup")
    print("=" * 60)
    print()
    
    # Get API credentials
    print("Step 1: Get your Telegram API credentials")
    print("Visit https://my.telegram.org/apps to create an application")
    print()
    
    api_id = os.getenv("SENTIMENT_TELEGRAM_API_ID")
    api_hash = os.getenv("SENTIMENT_TELEGRAM_API_HASH")
    
    if not api_id:
        api_id = input("Enter your Telegram API ID: ").strip()
    else:
        print(f"Using API ID from environment: {api_id}")
    
    if not api_hash:
        api_hash = input("Enter your Telegram API Hash: ").strip()
    else:
        print(f"Using API Hash from environment: {api_hash[:8]}...")
    
    try:
        api_id = int(api_id)
    except ValueError:
        print("Error: API ID must be a number")
        return False
    
    # Setup session directory
    session_dir = ".telegram_sessions"
    if not os.path.exists(session_dir):
        os.makedirs(session_dir, mode=0o700)
        print(f"\nCreated session directory: {session_dir}/")
    
    session_path = os.path.join(session_dir, "sentiment_bot")
    
    print()
    print("Step 2: Authenticate with Telegram")
    print()
    
    # Create client
    client = TelegramClient(
        session_path,
        api_id,
        api_hash,
        use_ipv6=True
    )
    
    try:
        await client.connect()
        
        # Check if already authorized
        if await client.is_user_authorized():
            print("✓ Already authenticated!")
            print(f"Session file: {session_path}.session")
            me = await client.get_me()
            print(f"Logged in as: {me.first_name} ({me.username or 'no username'})")
            return True
        
        # Request phone number
        phone = input("Enter your phone number (with country code, e.g., +1234567890): ").strip()
        
        # Send code request
        await client.send_code_request(phone)
        print(f"\n✓ Code sent to {phone}")
        
        # Get verification code
        code = input("Enter the verification code you received: ").strip()
        
        try:
            await client.sign_in(phone, code)
            
        except SessionPasswordNeededError:
            # 2FA enabled
            print("\nYour account has Two-Factor Authentication (2FA) enabled.")
            password = getpass("Enter your 2FA password: ")
            await client.sign_in(password=password)
        
        except PhoneCodeInvalidError:
            print("\nError: Invalid verification code")
            return False
        
        # Set secure permissions on session file
        session_file = f"{session_path}.session"
        if os.path.exists(session_file):
            os.chmod(session_file, 0o600)
        
        print()
        print("=" * 60)
        print("✓ Setup complete!")
        print("=" * 60)
        
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} ({me.username or 'no username'})")
        print(f"Session file: {session_file}")
        print()
        print("Security reminders:")
        print("- Session file contains authentication data")
        print("- Never commit session files to git")
        print("- Keep API credentials secure")
        print()
        print("Next steps:")
        print("1. Add API credentials to .env file:")
        print("   SENTIMENT_TELEGRAM_API_ID=your_api_id")
        print("   SENTIMENT_TELEGRAM_API_HASH=your_api_hash")
        print("2. Restart the sentiment server")
        print()
        
        return True
        
    except Exception as e:
        print(f"\nError during setup: {type(e).__name__}: {e}")
        return False
        
    finally:
        await client.disconnect()


async def test_connection():
    """Test the Telegram connection."""
    
    print("\n" + "=" * 60)
    print("Testing Telegram Connection")
    print("=" * 60)
    print()
    
    api_id = os.getenv("SENTIMENT_TELEGRAM_API_ID")
    api_hash = os.getenv("SENTIMENT_TELEGRAM_API_HASH")
    
    if not api_id or not api_hash:
        print("Error: SENTIMENT_TELEGRAM_API_ID and SENTIMENT_TELEGRAM_API_HASH must be set")
        return False
    
    session_path = os.path.join(".telegram_sessions", "sentiment_bot")
    
    client = TelegramClient(
        session_path,
        int(api_id),
        api_hash,
        use_ipv6=True
    )
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            print("✗ Not authorized. Run setup first.")
            return False
        
        me = await client.get_me()
        print(f"✓ Connected as: {me.first_name} ({me.username or 'no username'})")
        
        # Test fetching from a popular channel
        print("\nTesting channel access...")
        try:
            channel = await client.get_entity("cointelegraph")
            print(f"✓ Can access @cointelegraph ({channel.title})")
            
            # Fetch a few recent messages
            messages = await client.get_messages(channel, limit=5)
            print(f"✓ Fetched {len(messages)} recent messages")
            
        except Exception as e:
            print(f"✗ Error accessing channel: {e}")
            return False
        
        print("\n✓ All tests passed!")
        return True
        
    except Exception as e:
        print(f"✗ Connection error: {e}")
        return False
        
    finally:
        await client.disconnect()


def main():
    """Main entry point."""
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Test mode
        success = asyncio.run(test_connection())
    else:
        # Setup mode
        success = asyncio.run(setup_telegram_session())
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
