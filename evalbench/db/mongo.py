import motor.motor_asyncio

from evalbench.config import settings


def make_client() -> motor.motor_asyncio.AsyncIOMotorClient:
    """A fresh Mongo client. The RQ worker needs one per job so the motor
    client binds to that job's event loop, not a stale one."""
    return motor.motor_asyncio.AsyncIOMotorClient(
        settings.mongodb_url,
        maxPoolSize=50,
        minPoolSize=10,
        serverSelectionTimeoutMS=5000,
    )


# Long-lived client/db for the API process (single event loop).
client = make_client()

db = client[settings.mongodb_db]
