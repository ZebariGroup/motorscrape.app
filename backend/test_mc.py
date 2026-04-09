import asyncio
from app.schemas import VehicleListing
from app.services.marketcheck import enrich_with_marketcheck

async def main():
    listing = VehicleListing(vin="1G1AL58F877223009", mileage=136914, price=2995)
    result = await enrich_with_marketcheck([listing])
    print(result[0].model_dump(exclude_none=True))

asyncio.run(main())
