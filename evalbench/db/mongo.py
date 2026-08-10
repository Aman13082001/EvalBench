import motor.motor_asyncio
from evalbench.config import settings

client = motor.motor_asyncio.AsyncIOMotorClient(settings.mongodb_url)
db = client[settings.mongodb_db]