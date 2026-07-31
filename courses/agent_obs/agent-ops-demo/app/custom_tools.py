# This custom tool is to be called from the agent when the demo requests it.
# Background: when hardcoding the contents of the results, the agents are "too smart" and
# will not deterministically call the tool. Hence, the need for the dynamically generated output 
# in the body of the fake customer lookup function

import random
import time


def custom_db_lookup(customer_id: str = "demo-customer-001") -> dict:
    """
    Retrieve current customer context, including a fresh location snapshot.
    """

    delay_sec = random.uniform(1.0, 5.0)
    time.sleep(delay_sec)

    if random.random() < 0.3:
        raise RuntimeError("Customer location service timeout")


    lat = round(random.uniform(-90.0, 90.0), 6)
    lon = round(random.uniform(-180.0, 180.0), 6)
    ts = int(time.time())

    return {
        "customer_id": customer_id,
        "account_status": "active",
        "subscription_tier": "premium",
        "current_latitude": lat,
        "current_longitude": lon,
        "location_timestamp": ts,
    }

