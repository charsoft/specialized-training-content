### Be sure to run "pip install google-cloud-aiplatform --upgrade" in your environment first!

import asyncio
import json
import random
import requests
import vertexai

LOCATION = "us-central1"
PROJECT_ID = "REPLACE ME!"

if PROJECT_ID == "REPLACE ME!":
    raise ValueError("Please replace the PROJECT_ID variable with your project ID.")

client = vertexai.Client(
    location=LOCATION,
    project=PROJECT_ID
)

REASONING_ENGINE_ID = None

if REASONING_ENGINE_ID is None:
    try:
        with open("./deployment_metadata.json") as f:
            metadata = json.load(f)
            REASONING_ENGINE_ID = metadata.get("remote_agent_engine_id")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

print(f"Using REASONING_ENGINE_ID: {REASONING_ENGINE_ID}")
# Get the existing agent engine
remote_agent_engine = client.agent_engines.get(name=REASONING_ENGINE_ID)

prompts = {0: 'List the tables in the ecommerce BigQuery dataset',
           1: 'Where are our distribution centers?',
           2: 'Which user has placed the most orders?',
           3: 'Give me the schema of the orders table' } 

async def simulate_load() -> None:
    while True:
        async for event in remote_agent_engine.async_stream_query(
                message=prompts[random.randint(0,3)], user_id="test"
            ):
                if 'content' in event and 'parts' in event['content']:
                  print(event['content']['parts'][0])
                elif 'function_call' in event:
                  print(f"🔧 Tool Call: {event['function_call']['name']}")
                elif 'function_response' in event:
                  print(f"✅ Tool Response: {event['function_response']['name']}")

        await asyncio.sleep(1)


if __name__ == '__main__':
     asyncio.run(simulate_load())
