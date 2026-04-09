import asyncio
import httpx
import sqlite3
import json

async def main():
    # Get a recent VIN from local DB
    try:
        conn = sqlite3.connect('backend/data/accounts.sqlite3')
        c = conn.cursor()
        c.execute("SELECT vin FROM inventory_history WHERE vin IS NOT NULL ORDER BY updated_at DESC LIMIT 1")
        row = c.fetchone()
        vin = row[0] if row else "1G1AL58F877123456" # Fallback dummy VIN
        print(f"Testing with VIN: {vin}")
    except Exception as e:
        print(f"DB error: {e}")
        vin = "1G1AL58F877123456"

    api_key = "a2KjqPlk4nm6tM8BECcAIlAa1juSjj72"
    url = "https://marketcheck-prod.apigee.net/v2/search/car/active"
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params={"api_key": api_key, "vins": vin, "rows": 1})
        print(f"Status: {resp.status_code}")
        print(json.dumps(resp.json(), indent=2)[:500])

asyncio.run(main())
