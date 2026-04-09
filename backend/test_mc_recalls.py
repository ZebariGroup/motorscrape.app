import asyncio
import httpx
import json

async def main():
    vin = "1G1AL58F877223009" # Dummy VIN
    api_key = "a2KjqPlk4nm6tM8BECcAIlAa1juSjj72"
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"https://api.marketcheck.com/v2/safety/recalls", params={"api_key": api_key, "vin": vin})
            print(f"Recalls URL Status: {resp.status_code}")
            print(json.dumps(resp.json(), indent=2)[:1000])
        except Exception as e:
            print(f"Recalls URL failed: {e}")

asyncio.run(main())
