import os
from persistence.database import Database, DEFAULT_DB_PATH
from persistence.repositories import OrderRepository
from execution.reconciler import Reconciler


async def recover_incomplete_orders(db_path=None):
    repo=OrderRepository(Database(db_path or os.getenv('DERIV_DB_PATH') or DEFAULT_DB_PATH))
    return await Reconciler(repo).recover_incomplete_orders()
