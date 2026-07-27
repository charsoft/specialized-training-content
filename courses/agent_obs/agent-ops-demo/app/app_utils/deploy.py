# Copyright 2025 Google LLC
# Licensed under the Apache License, Version 2.0

import asyncio
import datetime
import importlib
import inspect
import json
import logging
import warnings
from typing import Any

import click
import google.auth
import vertexai
from vertexai._genai import _agent_engines_utils
from vertexai._genai.types import AgentEngine, AgentEngineConfig

warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    module="google.cloud.aiplatform",
)


def generate_class_methods_from_agent(agent_instance: Any) -> list[dict[str, Any]]:
    """Generate method specifications with schemas from agent register_operations()."""
    registered_operations = _agent_engines_utils._get_registered_operations(
        agent=agent_instance
    )
    class_methods_spec = _agent_engines_utils._generate_class_methods_spec_or_raise(
        agent=agent_instance,
        operations=registered_operations,
    )
    return [_agent_engines_utils._to_dict(method_spec) for method_spec in class_methods_spec]


def parse_key_value_pairs(kv_string: str | None) -> dict[str, str]:
    """Parse key-value pairs from a comma-separated KEY=VALUE string."""
    result: dict[str, str] = {}
    if kv_string:
        for pair in kv_string.split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                result[key.strip()] = value.strip()
            else:
                logging.warning("Skipping malformed key-value pair: %s", pair)
    return result


def write_deployment_metadata(
    remote_agent: Any,
    metadata_file: str = "deployment_metadata.json",
) -> None:
    """Write deployment metadata to file."""
    metadata = {
        "remote_agent_engine_id": remote_agent.api_resource.name,
        "deployment_timestamp": datetime.datetime.now().isoformat(),
    }
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    logging.info("Agent Engine ID written to %s", metadata_file)


def print_deployment_success(remote_agent: Any, location: str, project: str) -> None:
    """Print deployment success message with console URL."""
    resource_name_parts = remote_agent.api_resource.name.split("/")
    agent_engine_id = resource_name_parts[-1]
    project_number = resource_name_parts[1]

    print("\n✅ Deployment successful!")

    service_account = remote_agent.api_resource.spec.service_account
    if service_account:
        print(f"Service Account: {service_account}")
    else:
        default_sa = f"service-{project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
        print(f"Service Account: {default_sa}")

    playground_url = (
        f"https://console.cloud.google.com/vertex-ai/agents/locations/"
        f"{location}/agent-engines/{agent_engine_id}/playground?project={project}"
    )
    print(f"\n📊 Open Console Playground: {playground_url}\n")


@click.command()
@click.option("--project", default=None)
@click.option("--location", default="us-central1")
@click.option("--display-name", default="agent-ops-demo")
@click.option(
    "--description",
    default="A base ReAct agent built with Google's Agent Development Kit (ADK)",
)
@click.option(
    "--source-packages",
    multiple=True,
    default=["./app"],
)
@click.option(
    "--entrypoint-module",
    default="app.agent_engine_app",
)
@click.option(
    "--entrypoint-object",
    default="agent_engine",
)
@click.option(
    "--requirements-file",
    default="app/app_utils/.requirements.txt",
)
@click.option("--set-env-vars", default=None)
@click.option("--labels", default=None)
@click.option("--service-account", default=None)
@click.option("--min-instances", type=int, default=1)
@click.option("--max-instances", type=int, default=10)
@click.option("--cpu", default="4")
@click.option("--memory", default="8Gi")
@click.option("--container-concurrency", type=int, default=9)
@click.option("--num-workers", type=int, default=1)
def deploy_agent_engine_app(
    project: str | None,
    location: str,
    display_name: str,
    description: str,
    source_packages: tuple[str, ...],
    entrypoint_module: str,
    entrypoint_object: str,
    requirements_file: str,
    set_env_vars: str | None,
    labels: str | None,
    service_account: str | None,
    min_instances: int,
    max_instances: int,
    cpu: str,
    memory: str,
    container_concurrency: int,
    num_workers: int,
) -> AgentEngine:
    """Deploy the agent engine app to Vertex AI."""
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    env_vars = parse_key_value_pairs(set_env_vars)
    labels_dict = parse_key_value_pairs(labels)

    if "NUM_WORKERS" not in env_vars:
        env_vars["NUM_WORKERS"] = str(num_workers)

    if not project:
        _, project = google.auth.default()

    env_vars["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "true"
    env_vars["OTEL_SEMCONV_STABILITY_OPT_IN"] = "gen_ai_latest_experimental"
    env_vars["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "EVENT_ONLY"
    env_vars["GOOGLE_CLOUD_PROJECT"] = project
    env_vars["OTEL_EXPORTER_GCP_TRACE_PROJECT_ID"] = project

    print(
        """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║      🤖 DEPLOYING AGENT TO VERTEX AI AGENT ENGINE 🤖      ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
"""
    )

    click.echo("\n📋 Deployment Parameters:")
    click.echo(f" Project: {project}")
    click.echo(f" Location: {location}")
    click.echo(f" Display Name: {display_name}")
    click.echo(f" Min Instances: {min_instances}")
    click.echo(f" Max Instances: {max_instances}")
    click.echo(f" CPU: {cpu}")
    click.echo(f" Memory: {memory}")
    click.echo(f" Container Concurrency: {container_concurrency}")
    click.echo(f" NUM_WORKERS: {env_vars.get('NUM_WORKERS')}")
    click.echo(
        " Telemetry: "
        f"GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY={env_vars['GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY']}, "
        f"OTEL_SEMCONV_STABILITY_OPT_IN={env_vars['OTEL_SEMCONV_STABILITY_OPT_IN']}, "
        f"OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT={env_vars['OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT']}"
    )
    if service_account:
        click.echo(f" Service Account: {service_account}")
    click.echo("")

    client = vertexai.Client(project=project, location=location)
    vertexai.init(project=project, location=location)

    logging.info("Importing %s.%s", entrypoint_module, entrypoint_object)
    module = importlib.import_module(entrypoint_module)
    agent_instance = getattr(module, entrypoint_object)

    if inspect.iscoroutine(agent_instance):
        logging.info("Detected coroutine, awaiting %s...", entrypoint_object)
        agent_instance = asyncio.run(agent_instance)

    class_methods_list = generate_class_methods_from_agent(agent_instance)

    config = AgentEngineConfig(
        display_name=display_name,
        description=description,
        source_packages=list(source_packages),
        entrypoint_module=entrypoint_module,
        entrypoint_object=entrypoint_object,
        class_methods=class_methods_list,
        env_vars=env_vars,
        service_account=service_account,
        requirements_file=requirements_file,
        labels=labels_dict,
        min_instances=min_instances,
        max_instances=max_instances,
        resource_limits={"cpu": cpu, "memory": memory},
        container_concurrency=container_concurrency,
        agent_framework="google-adk",
    )

    existing_agents = list(client.agent_engines.list())
    matching_agents = [
        agent
        for agent in existing_agents
        if agent.api_resource.display_name == display_name
    ]

    if matching_agents:
        click.echo(f"\n📝 Updating existing agent: {display_name}")
    else:
        click.echo(f"\n🚀 Creating new agent: {display_name}")

    click.echo("🚀 Deploying to Vertex AI Agent Engine (this can take 3-5 minutes)...")

    if matching_agents:
        remote_agent = client.agent_engines.update(
            name=matching_agents[0].api_resource.name,
            config=config,
        )
    else:
        remote_agent = client.agent_engines.create(config=config)

    write_deployment_metadata(remote_agent)
    print_deployment_success(remote_agent, location, project)
    return remote_agent


if __name__ == "__main__":
    deploy_agent_engine_app()
