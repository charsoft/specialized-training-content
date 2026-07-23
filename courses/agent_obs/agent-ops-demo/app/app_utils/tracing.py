# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
from collections.abc import Sequence
from typing import Any

import google.cloud.storage as storage
from google.cloud import logging as google_cloud_logging
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult


class OpenTelemetryLogFilter(logging.Filter):
    """
    A logging filter that enriches log records with OpenTelemetry trace/span IDs
    and agent metadata for proper GCP log correlation.
    """

    def filter(self, record):
        """
        Enrich log record with OpenTelemetry span context and agent metadata.

        :param record: The log record to filter
        :return: True to allow the record to be logged
        """
        # 1. Fetch the active OpenTelemetry span
        current_span = trace.get_current_span()
        if current_span and current_span.get_span_context().is_valid:
            # 2. Extract standard trace/span IDs for GCP correlation
            ctx = current_span.get_span_context()
            record.trace_id = f"{ctx.trace_id:032x}"
            record.span_id = f"{ctx.span_id:016x}"

            # 3. Pull ADK attributes from the active span
            if hasattr(current_span, "attributes"):
                record.vertex_event_id = current_span.attributes.get(
                    "gcp.vertex.agent.event_id", "unknown"
                )
                record.vertex_agent_name = current_span.attributes.get(
                    "gen_ai.agent.name", "unknown"
                )
            else:
                record.vertex_event_id = "unknown"
                record.vertex_agent_name = "unknown"
        else:
            record.trace_id = ""
            record.span_id = ""
            record.vertex_event_id = "unknown"
            record.vertex_agent_name = "unknown"
        return True


class JsonFormatter(logging.Formatter):
    """
    A JSON formatter that structures log entries with proper GCP correlation fields
    and agent metadata for Log-based metrics.
    """

    def format(self, record):
        """
        Format a log record as a JSON string with GCP correlation.

        :param record: The log record to format
        :return: JSON-formatted log entry string
        """
        trace_id = getattr(record, "trace_id", "")
        span_id = getattr(record, "span_id", "")
        project_id = getattr(record, "project_id", "YOUR_PROJECT_ID")

        log_entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
        }

        # Add GCP correlation fields if trace_id is available
        if trace_id:
            log_entry["logging.googleapis.com/trace"] = (
                f"projects/{project_id}/traces/{trace_id}"
            )
            log_entry["logging.googleapis.com/spanId"] = span_id

        # Add agent metadata for Log-based metrics
        log_entry["vertex_agent"] = {
            "event_id": getattr(record, "vertex_event_id", "unknown"),
            "agent_name": getattr(record, "vertex_agent_name", "unknown"),
        }

        return json.dumps(log_entry)


class CloudTraceLoggingSpanExporter(CloudTraceSpanExporter):
    """
    An extended version of CloudTraceSpanExporter that logs span data to Google Cloud Logging
    and handles large attribute values by storing them in Google Cloud Storage.

    This class helps bypass the 256 character limit of Cloud Trace for attribute values
    by leveraging Cloud Logging (which has a 256KB limit) and Cloud Storage for larger payloads.
    """

    def __init__(
        self,
        logging_client: google_cloud_logging.Client | None = None,
        storage_client: storage.Client | None = None,
        bucket_name: str | None = None,
        debug: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the exporter with Google Cloud clients and configuration.

        :param logging_client: Google Cloud Logging client
        :param storage_client: Google Cloud Storage client
        :param bucket_name: Name of the GCS bucket to store large payloads
        :param debug: Enable debug mode for additional logging
        :param kwargs: Additional arguments to pass to the parent class
        """
        super().__init__(**kwargs)
        self.debug = debug
        self.logging_client = logging_client or google_cloud_logging.Client(
            project=self.project_id
        )
        self.logger = self.logging_client.logger(__name__)
        self.storage_client = storage_client or storage.Client(project=self.project_id)
        self.bucket_name = bucket_name or f"{self.project_id}-agent-ops-demo-logs"
        self.bucket = self.storage_client.bucket(self.bucket_name)

        # Setup logging with OpenTelemetry filter and JSON formatter
        self._setup_logging()

    def _setup_logging(self) -> None:
        """
        Setup the standard logging module with OpenTelemetry filter and JSON formatter.
        """
        # Get or create logger for this module
        module_logger = logging.getLogger(__name__)
        
        # Remove existing handlers to avoid duplicates
        module_logger.handlers = []
        
        # Create console handler with JSON formatter
        handler = logging.StreamHandler()
        handler.addFilter(OpenTelemetryLogFilter())
        
        formatter = JsonFormatter()
        handler.setFormatter(formatter)
        
        module_logger.addHandler(handler)
        module_logger.setLevel(logging.INFO)

    def sanitize_attrs(self, attributes: dict) -> dict:
        """Helper function to convert dict attributes to JSON strings."""
        clean = {}
        for key, val in attributes.items():
            if isinstance(val, dict):
                clean[key] = json.dumps(val)
            else:
                clean[key] = val
        return clean

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """
        Export the spans to Google Cloud Logging and Cloud Trace.

        :param spans: A sequence of spans to export
        :return: The result of the export operation
        """
        for span in spans:
            span_context = span.get_span_context()
            trace_id = format(span_context.trace_id, "x")
            span_id = format(span_context.span_id, "x")
            span_dict = json.loads(span.to_json())

            # 1. --- SANITIZE ATTRIBUTES (Converts dicts like tool_call_args to strings) ---
            if "attributes" in span_dict:
                span_dict["attributes"] = self.sanitize_attrs(
                    span_dict["attributes"]
                )

            # 2. --- BUBBLE UP TOKENS DIRECTLY ---
            attrs = span_dict.get("attributes", {})
            input_tokens = (
                attrs.get("gen_ai.usage.input_tokens")
                or attrs.get("llm.token_count.prompt")
                or 0
            )
            output_tokens = (
                attrs.get("gen_ai.usage.output_tokens")
                or attrs.get("llm.token_count.candidates")
                or 0
            )
            total_tokens = input_tokens + output_tokens
            
            # 3. --- CONSOLE WRITE-LINE (Creates top-level jsonPayload in Cloud Logging) ---
            print(
                json.dumps(
                    {
                        "event": "token_summary",
                        "trace_id": trace_id,
                        "span_id": span_id,
                        "total_tokens": total_tokens,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    }
                )
            )

            # 4. --- EXISTING SPAN EXPORT LOGIC ---
            span_dict["trace"] = f"projects/{self.project_id}/traces/{trace_id}"
            span_dict["span_id"] = span_id

            # 5. --- EXTRACT AGENT METADATA ---
            vertex_event_id = attrs.get("gcp.vertex.agent.event_id", "unknown")
            vertex_agent_name = attrs.get("gen_ai.agent.name", "unknown")
            span_dict["vertex_agent"] = {
                "event_id": vertex_event_id,
                "agent_name": vertex_agent_name,
            }

            span_dict = self._process_large_attributes(
                span_dict=span_dict, span_id=span_id
            )

            if self.debug:
                print(span_dict)

            # Log the span data to Google Cloud Logging
            self.logger.log_struct(
                span_dict,
                labels={
                    "type": "agent_telemetry",
                    "service_name": "agent-ops-demo",
                },
                severity="INFO",
            )

        # Export spans to Google Cloud Trace using the parent class method
        return super().export(spans)

    def store_in_gcs(self, content: str, span_id: str) -> str:
        """
        Store large content in Google Cloud Storage.

        :param content: The content to store
        :param span_id: The ID of the span
        :return: The GCS URI of the stored content
        """
        if not self.storage_client.bucket(self.bucket_name).exists():
            logging.warning(
                f"Bucket {self.bucket_name} not found. "
                "Unable to store span attributes in GCS."
            )
            return "GCS bucket not found"

        blob_name = f"spans/{span_id}.json"
        blob = self.bucket.blob(blob_name)

        blob.upload_from_string(content, "application/json")
        return f"gs://{self.bucket_name}/{blob_name}"

    def _process_large_attributes(self, span_dict: dict, span_id: str) -> dict:
        """
        Process large attribute values by storing them in GCS if they exceed the size
        limit of Google Cloud Logging.

        :param span_dict: The span data dictionary
        :param span_id: The span ID
        :return: The updated span dictionary
        """
        attributes = span_dict["attributes"]
        if len(json.dumps(attributes).encode()) > 255 * 1024:  # 250 KB
            # Store large payload in GCS
            attributes_payload = dict(attributes.items())
            gcs_uri = self.store_in_gcs(json.dumps(attributes_payload), span_id)

            # Keep only the URI pointers, not the original large attributes
            attributes_retain = {
                "uri_payload": gcs_uri,
                "url_payload": (
                    f"https://storage.mtls.cloud.google.com/"
                    f"{self.bucket_name}/spans/{span_id}.json"
                ),
            }

            span_dict["attributes"] = attributes_retain
            logging.info(
                "Length of payload span above 250 KB, storing attributes in GCS "
                "to avoid large log entry errors"
            )

        return span_dict
