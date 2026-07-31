from google.adk.agents import Agent
from google.adk.apps.app import App
from google.adk.tools.bigquery import BigQueryCredentialsConfig, BigQueryToolset
from opentelemetry import trace
## ----- DEMO NOTES: first demo using custom tools, make sure to run the non-OTEL instrumented method below
from app.custom_tools import custom_db_lookup
#  from app.custom_tools_with_trace import custom_db_lookup #swap this one for the one above when showing tooling vs no tooling
### ---- END DEMO NOTES

import google.auth
import dotenv
import random
import time
import json



dotenv.load_dotenv()

credentials, _ = google.auth.default()
credentials_config = BigQueryCredentialsConfig(credentials=credentials)
bigquery_toolset = BigQueryToolset(
  credentials_config=credentials_config
)

PROJECT_ID = '<change me>'

def possible_bottleneck() -> dict[str, int]:
  """Adds a random delay between 1 and 5 seconds to the response.

  Returns:
      A dict with the delay in milliseconds. For example: {'delay': 2500}
  """
  span = trace.get_current_span()
  span.set_attribute("customer_tier", "premium")
  # call that endpoint, redact that data, on success, do this:
  span.set_attribute("pii_redaction_status", "SUCCESS")

  # Change 0.1 to 0.3 or 0.5 so it triggers 30-50% of the time during testing/traces
  if random.random() < 0.4:
    delay_sec = random.uniform(1.0, 5.0)  # Guaranteed 1.0s to 5.0s delay
    time.sleep(delay_sec)
    delay_ms = int(delay_sec * 1000)
  else:
    delay_ms = 0

  return {"delay": delay_ms}

### ---- DEMO NOTES ----
# for first few demos, use this one. No custom tools, no custom instructions, just basic trace
root_agent = Agent(   #rename the root_agent to root_agent_v1 when switching over to the custom tools demo
 model="gemini-2.5-flash",
 name="bigquery_agent",
 description="Agent that answers questions about BigQuery data by executing SQL queries.",
 instruction=(
     f"""
       You are a BigQuery data analysis agent.
       You are able to answer questions on data stored in project-id: '{PROJECT_ID}' on the `ecommerce` dataset.
       Before every request to the bigquery_toolset tools, use the possible_bottleneck tool to add a random delay between 0 and 1000 milliseconds.
     """
 ),
 tools=[bigquery_toolset, possible_bottleneck]
)

#this calls the custom db lookup tool
root_agent_v2 = Agent(  #rename the root_agent to root_agent when switching over to the custom tools demo
 model="gemini-2.5-flash",
 name="bigquery_agent",
 description="Agent that answers questions about BigQuery data by executing SQL queries.",
 instruction=(
     f"""
       You are a BigQuery data analysis agent.

      You are able to answer questions on data stored in project-id: '{PROJECT_ID}'
      on the `ecommerce` dataset.

      At the start of every new conversation, first call custom_db_lookup
      before doing anything else.

      After that, continue handling the user's request normally.

      Use the custom_db_lookup tool whenever customer account status,
      subscription tier, or internal account lookup information is needed.

      Before every request to the bigquery_toolset tools, use the possible_bottleneck tool.
     """
 ),
 tools=[bigquery_toolset, possible_bottleneck, custom_db_lookup]
)
app = App(root_agent=root_agent, name="app")
