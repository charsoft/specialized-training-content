# Copyright 2025 Google LLC
# Licensed under the Apache License, Version 2.0

# mypy: disable-error-code="attr-defined,arg-type"

import logging
import os
from typing import Any

import google.auth
import vertexai
from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from google.cloud import logging as google_cloud_logging
from opentelemetry import trace
from opentelemetry.sdk.trace import export
from vertexai.agent_engines.templates.adk import AdkApp

from app.agent import app as adk_app
from app.app_utils.tracing import CloudTraceLoggingSpanExporter
from app.app_utils.typing import Feedback


class AgentEngineApp(AdkApp):
    def set_up(self) -> None:
        """Set up logging and tracing for the agent engine app."""
        super().set_up()

        logging.basicConfig(level=logging.INFO)
        self.app_logger = logging.getLogger("agent_ops_demo")
        self.app_logger.setLevel(logging.INFO)

        self.logging_client = google_cloud_logging.Client()
        self.cloud_logger = self.logging_client.logger("agent_ops_demo")

        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        provider = trace.get_tracer_provider()

        processor = export.BatchSpanProcessor(
            CloudTraceLoggingSpanExporter(
                project_id=project_id,
                logging_client=self.logging_client,
                log_name="agent_ops_span_summaries",
            )
        )

        if hasattr(provider, "add_span_processor"):
            provider.add_span_processor(processor)
            self.app_logger.info("Attached CloudTraceLoggingSpanExporter to existing tracer provider")
        else:
            self.app_logger.warning(
                "Global tracer provider does not support add_span_processor; "
                "custom span summary exporter was not attached."
            )

    def register_feedback(self, feedback: dict[str, Any]) -> None:
        """Collect and log feedback."""
        feedback_obj = Feedback.model_validate(feedback)
        self.cloud_logger.log_struct(
            feedback_obj.model_dump(),
            severity="INFO",
            labels={"source": "register_feedback"},
        )

    def register_operations(self) -> dict[str, list[str]]:
        """Register operations, including feedback registration."""
        operations = super().register_operations()
        operations[""] = operations.get("", []) + ["register_feedback"]
        return operations

#This is safer because the deploy command already knows the intended project, 
#and the Cloud Trace exporter documentation explicitly expects a plain GCP project ID, 
#including support for exporter-specific project configuration.
_, default_project_id = google.auth.default()
project_id = (
    os.environ.get("OTEL_EXPORTER_GCP_TRACE_PROJECT_ID")
    or os.environ.get("GOOGLE_CLOUD_PROJECT")
    or default_project_id
)
vertexai.init(project=project_id, location="us-central1")

artifacts_bucket_name = os.environ.get("ARTIFACTS_BUCKET_NAME")

agent_engine = AgentEngineApp(
    app=adk_app,
    artifact_service_builder=lambda: GcsArtifactService(
        bucket_name=artifacts_bucket_name
    )
    if artifacts_bucket_name
    else InMemoryArtifactService(),
)
