import asyncio
from dataclasses import dataclass
from typing import Any
from typing import Optional

from telliot_feeds.feeds import DataFeed
from telliot_feeds.reporters.tellor_360 import Tellor360Reporter
from telliot_feeds.utils.log import get_logger
from telliot_feeds.utils.reporter_utils import current_time

logger = get_logger(__name__)


@dataclass
class GetDataBefore:
    retrieved: bool
    value: bytes
    timestampRetrieved: int


@dataclass
class ConditionalReporter(Tellor360Reporter):
    """Backup Reporter that inherits from Tellor360Reporter and
    implements conditions when intended as backup to chainlink"""

    def __init__(
        self,
        stale_timeout: int,
        max_price_change: float,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.stale_timeout = stale_timeout
        self.max_price_change = max_price_change

    async def get_tellor_latest_data(self) -> Optional[GetDataBefore]:
        """Get latest data from tellor oracle (getDataBefore with current time)

        Returns:
        - Optional[GetDataBefore]: latest data from tellor oracle
        """
        if self.datafeed is None:
            logger.debug(f"no datafeed set: {self.datafeed}")
            return None
        data, status = await self.oracle.read("getDataBefore", self.datafeed.query.query_id, current_time())
        if not status.ok:
            logger.warning(f"error getting tellor data: {status.e}")
            return None
        return GetDataBefore(*data)
    
    async def fetch_median_value(self) -> Optional[DataFeed[Any]]:
        """Fetches datafeed

        If the user did not select a query tag, there will have been no datafeed passed to
        the reporter upon instantiation.
        If the user uses the random feeds flag, the datafeed will be chosen randomly.
        If the user did not select a query tag or use the random feeds flag, the datafeed will
        be chosen based on the most funded datafeed in the AutoPay contract.

        If the no-rewards-check flag is used, the reporter will not check profitability or
        available tips for the datafeed unless the user has not selected a query tag or
        used the random feeds flag.
        """
        # reset autopay tip every time fetch_datafeed is called
        # so that tip is checked fresh every time and not carry older tips
        self.autopaytip = 0
        # TODO: This should be removed and moved to profit check method perhaps
        if self.check_rewards:
            # calculate tbr and
            _ = await self.rewards()

        if self.use_random_feeds:
            self.datafeed = suggest_random_feed()

        # Fetch datafeed based on whichever is most funded in the AutoPay contract
        if self.datafeed is None:
            suggested_feed, tip_amount = await get_feed_and_tip(self.autopay)

            if suggested_feed is not None and tip_amount is not None:
                logger.info(f"Most funded datafeed in Autopay: {suggested_feed.query.type}")
                logger.info(f"Tip amount: {self.to_ether(tip_amount)}")
                self.autopaytip += tip_amount

                self.datafeed = suggested_feed
                return self.datafeed

        return self.datafeed

    async def conditions_met(self) -> bool:
        """Trigger methods to check conditions if reporting spot is necessary

        Returns:
        - bool: True if conditions are met, False otherwise
        """
        logger.info("checking conditions and reporting if necessary")
        if self.datafeed is None:
            logger.debug(f"no datafeed was setß: {self.datafeed}. Please provide a spot-price query type (see --help)")
            return False
        tellor_data = await self.get_tellor_latest_data()
        time = current_time()
        time_passed_since_tellor_report = time - tellor_data.timestampRetrieved if tellor_data else time
        tellor_value = tellor_data.value
        if tellor_data is None:
            logger.debug("tellor data returned None")
            return True
        elif not tellor_data.retrieved:
            logger.debug(f"No oracle submissions in tellor for query: {self.datafeed.query.descriptor}")
            return True
        elif time_passed_since_tellor_report > self.stale_timeout:
            logger.debug(f"tellor data is stale, time elapsed since last report: {time_passed_since_tellor_report}")
            return True
        eilf tellor_value
        else:
            logger.info(f"tellor {self.datafeed.query.descriptor} data is recent enough")
            return False






    async def report(self, report_count: Optional[int] = None) -> None:
        """Submit values to Tellor oracles on an interval."""

        while report_count is None or report_count > 0:
            online = await self.is_online()
            if online:
                if self.has_native_token():
                    if await self.conditions_met():
                        _, _ = await self.report_once()
                    else:
                        logger.info("feeds are recent enough, no need to report")

            else:
                logger.warning("Unable to connect to the internet!")

            logger.info(f"Sleeping for {self.wait_period} seconds")
            await asyncio.sleep(self.wait_period)

            if report_count is not None:
                report_count -= 1
