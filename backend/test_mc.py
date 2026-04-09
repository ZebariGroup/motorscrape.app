import asyncio

from app.services.marketcheck import fetch_marketcheck_details

async def main():
    result = await fetch_marketcheck_details("1G1AL58F877223009", 136914)
    print(result)

asyncio.run(main())
