# This is the same custom tool, similar to the non-decorated custom tool.
# Run this demo to show the difference between a non-instrumented call to a custom tool vs. 
# an OTEL instrumented call to the same functionality.

# Ideally, the traced span will have more details 

import random
import time
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer("app.custom_tools")

def custom_db_lookup(customer_id: str = "demo-customer-001") -> dict:
    with tracer.start_as_current_span("Tool: custom_db_lookup") as span:
        span.set_attribute("tool.name", "custom_db_lookup")
        span.set_attribute("customer.id", customer_id)

        try:
            delay_sec = random.uniform(1.0, 5.0)
            delay_ms = int(delay_sec * 1000)
            span.set_attribute("tool.simulated_delay_ms", delay_ms)

            time.sleep(delay_sec)

            if random.random() < 0.3:
                raise RuntimeError("Customer location service timeout")

            lat = round(random.uniform(-90.0, 90.0), 6)
            lon = round(random.uniform(-180.0, 180.0), 6)
            ts = int(time.time())

            span.set_attribute("customer.current_latitude", lat)
            span.set_attribute("customer.current_longitude", lon)
            span.set_attribute("tool.success", True)

            return {
                "customer_id": customer_id,
                "account_status": "active",
                "subscription_tier": "premium",
                "current_latitude": lat,
                "current_longitude": lon,
                "location_timestamp": ts,
                "delay_ms": delay_ms,
            }

        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.set_attribute("tool.success", False)
            raise
