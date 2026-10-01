"""One durable write claim per logical order. A timeout never causes a second buy."""
import asyncio
from domain.order import OrderStatus as S


class NotSentError(Exception):
    """The adapter can prove no write was attempted."""


class BrokerRejectedError(Exception):
    """Broker returned an explicit application-level rejection."""


class UnknownOutcomeError(Exception):
    """Send was attempted; broker may have committed the write."""


class OrderEngine:
    def __init__(self, repository):
        self.repo = repository

    async def execute(self, order_id, adapter, risk_check=None):
        order, claimed = self.repo.claim_submission(order_id, risk_check)
        if not claimed:
            return order
        intent = self.repo.intent(order.intent_id)
        try:
            receipt = await (adapter.place_order(intent, order) if order.action == 'BUY' else adapter.close_order(intent, order))
            if not receipt.get('contract_id'):
                raise UnknownOutcomeError('Missing broker contract identity')
        except asyncio.CancelledError:
            self.repo.transition(order_id,S.UNKNOWN,'submission_cancelled',changes={'last_error':'CANCELLED_AFTER_CLAIM'})
            raise
        except (NotSentError, BrokerRejectedError) as exc:
            return self.repo.transition(order_id, S.REJECTED, type(exc).__name__, changes={'last_error': type(exc).__name__})
        except Exception as exc:
            return self.repo.transition(order_id, S.UNKNOWN, 'outcome_unknown', changes={'last_error': type(exc).__name__})
        return self.repo.acknowledge(order_id, receipt)
