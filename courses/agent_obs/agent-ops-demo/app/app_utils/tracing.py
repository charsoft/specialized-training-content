# Copyright 2025 Google LLC
# Licensed under the Apache License, Version 2.0

import json
from collections.abc import Sequence
from typing import Any

import google.cloud.storage as storage
from google.cloud import logging as google_cloud_logging
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult


class CloudTraceLoggingSpanExporter(CloudTraceSpanExporter):
    """
    Cloud Trace exporter that also writes structured span summaries to Cloud Logging.
    """

    def __init__(
        self,
        logging_client: google_cloud_logging.Client | None = None,
        storage_client: storage.Client | None = None,
        bucket_name: str | None = None,
        log_name: str = "agent_ops_span_summaries",
        debug: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.debug = debug
        self.logging_client = logging_client or google_cloud_logging.Client(
            project=self.project_id
        )
        self.storage_client = storage_client or storage.Client(project=self.project_id)
        self.bucket_name = bucket_name or f"{self.project_id}-agent-ops-demo-logs"
        self.bucket = self.storage_client.bucket(self.bucket_name)
        self.cloud_logger = self.logging_client.logger(log_name)

    def sanitize_attrs(self, attributes: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, val in attributes.items():
            if isinstance(val, dict):
                clean[key] = json.dumps(val)
            else:
                clean[key] = val
        return clean

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            try:
                span_context = span.get_span_context()
                trace_id = f"{span_context.trace_id:032x}"
                span_id = f"{span_context.span_id:016x}"

                try:
                    span_dict = json.loads(span.to_json())
                    attrs = span_dict.get("attributes", {})
                except Exception:
                    attrs = dict(span.attributes) if hasattr(span, "attributes") else {}

                clean_attrs = self.sanitize_attrs(attrs)

                input_tokens = (
                    clean_attrs.get("gen_ai.usage.input_tokens")
                    or clean_attrs.get("llm.token_count.prompt")
                    or 0
                )
                output_tokens = (
                    clean_attrs.get("gen_ai.usage.output_tokens")
                    or clean_attrs.get("llm.token_count.candidates")
                    or 0
                )
                total_tokens = int(input_tokens) + int(output_tokens)

                vertex_event_id = clean_attrs.get("gcp.vertex.agent.event_id", "unknown")
                vertex_agent_name = clean_attrs.get("gen_ai.agent.name", "unknown")

                payload = {
                    "message": f"Agent {vertex_agent_name} telemetry metrics summary.",
                    "vertex_agent": {
                        "event_id": vertex_event_id,
                        "agent_name": vertex_agent_name,
                    },
                    "usage": {
                        "input_tokens": int(input_tokens),
                        "output_tokens": int(output_tokens),
                        "total_tokens": int(total_tokens),
                    },
                    "span": {
                        "name": getattr(span, "name", "unknown"),
                        "trace_id": trace_id,
                        "span_id": span_id,
                    },
                }

                self.cloud_logger.log_struct(
                    payload,
                    severity="INFO",
                    labels={"source": "CloudTraceLoggingSpanExporter"},
                    trace=f"projects/{self.project_id}/traces/{trace_id}",
                    span_id=span_id,
                )

            except Exception as exc:
                self.cloud_logger.log_struct(
                    {
                        "message": "CRITICAL EXPORTER FAILURE",
                        "error": str(exc),
                    },
                    severity="ERROR",
                    labels={"source": "CloudTraceLoggingSpanExporter"},
                )

        try:
            for span in spans:
                if hasattr(span, "_attributes") and span._attributes:
                    keys_to_clear = [
                        k for k, v in span._attributes.items() if isinstance(v, dict)
                    ]
                    for key in keys_to_clear:
                        span._attributes[key] = json.dumps(span._attributes[key])

            return super().export(spans)

        except Exception as exc:
            self.cloud_logger.log_struct(
                {
                    "message": "PARENT EXPORTER TRACE WARNING CAPTURED",
                    "error": str(exc),
                },
                severity="WARNING",
                labels={"source": "CloudTraceLoggingSpanExporter"},
            )
            return SpanExportResult.SUCCESS
