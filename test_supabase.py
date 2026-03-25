import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.abspath("backend"))

from app.db.supabase_store import get_supabase_store

def test_supabase():
    try:
        store = get_supabase_store()
        print("Successfully initialized Supabase client.")
        
        # Test anonymous usage
        anon_key = "test_anon_key_123"
        print(f"Testing anon usage for {anon_key}...")
        
        # Get current
        current = store.anon_get(anon_key)
        print(f"Current anon count: {current}")
        
        # Increment
        new_count = store.anon_increment(anon_key)
        print(f"New anon count: {new_count}")
        assert new_count == current + 1
        
        # Test rate limits
        bucket = "test_bucket_123"
        print(f"Testing rate limit for {bucket}...")
        allowed = store.rate_tick(bucket, limit=10)
        print(f"Rate tick allowed: {allowed}")
        
        print("Supabase connection and basic operations successful!")
    except Exception as e:
        print(f"Error testing Supabase: {e}")

if __name__ == "__main__":
    test_supabase()
