import motor.motor_asyncio

from evalbench.config import settings


client = motor.motor_asyncio.AsyncIOMotorClient(
    settings.mongodb_url,
    maxPoolSize=50,
    minPoolSize=10,
    serverSelectionTimeoutMS=5000,
)

db = client[settings.mongodb_db]
