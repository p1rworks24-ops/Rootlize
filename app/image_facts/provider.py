"""First-Vision image facts: one request per image, no eval resend."""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from io import BytesIO
import json
import time

from PIL import Image, ImageOps

from app.image_facts.format import prepare_facts_record
from app.image_facts.schema import (
    DEFAULT_IMAGE_DETAIL,
    DEFAULT_MAX_EDGE,
    FACT_PROMPT,
    FACTS_PROMPT_VERSION,
    FACTS_USER_PREFIX,
    fact_schema,
    unknown_facts_record,
)
from app.ai_budget import (
    KIND_VISION,
    OPERATION_FACTS_GENERATE,
    AiBudgetExceeded,
    AiRequestIntent,
    check_ai_budget,
)
from app.ai_proxy import invoke_ai_proxy, use_direct_ai_provider
from app.ai_proxy.errors import AiProxyError
from app.relevance import RelevanceImage, RelevanceProviderError
from app.relevance.openai_provider import (
    OpenAIImageRelevanceProvider,
    _BatchResult,
    _diagnostics_logger,
    _is_cancelled,
)


@dataclass(frozen=True)
class FactsRun:
    results: tuple[dict, ...]
    failed_image_ids: tuple[int, ...] = ()
    request_count: int = 0
    sent_image_count: int = 0
    resize_seconds: float = 0.0
    api_seconds: float = 0.0
    total_seconds: float = 0.0
    retry_count: int = 0
    request_attempt_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)


def _encode_pil(image: Image.Image, *, max_edge: int) -> tuple[str, int, int]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90, optimize=True)
    raw = buffer.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii"), image.width, image.height


def multiscale_views(path, *, max_edge: int = DEFAULT_MAX_EDGE) -> list[tuple[str, str, int, int]]:
    with Image.open(path) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        overview_url, width, height = _encode_pil(source.copy(), max_edge=max_edge)
        views = [("Full image overview", overview_url, width, height)]
        if source.width < 900 and source.height < 700:
            return views
        overlap = 0.08
        x_mid = source.width // 2
        y_mid = source.height // 2
        x_pad = int(source.width * overlap)
        y_pad = int(source.height * overlap)
        boxes = (
            (0, 0, min(source.width, x_mid + x_pad), min(source.height, y_mid + y_pad)),
            (max(0, x_mid - x_pad), 0, source.width, min(source.height, y_mid + y_pad)),
            (0, max(0, y_mid - y_pad), min(source.width, x_mid + x_pad), source.height),
            (max(0, x_mid - x_pad), max(0, y_mid - y_pad), source.width, source.height),
        )
        for index, box in enumerate(boxes, 1):
            data_url, crop_w, crop_h = _encode_pil(source.crop(box), max_edge=1024)
            views.append((f"Detail region {index} of 4", data_url, crop_w, crop_h))
        return views


class ImageFactsProvider(OpenAIImageRelevanceProvider):
    """Query-free facts generation. One Vision request per image."""

    budget_operation = OPERATION_FACTS_GENERATE
    budget_kind = KIND_VISION

    def classify(self, query, images, *, cancelled=None):
        raise RuntimeError(
            "ImageFactsProvider.index() must be used; classify() would send a query."
        )

    def index(
        self,
        images: Sequence[RelevanceImage],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> FactsRun:
        if self._requires_local_api_key() and not self.api_key:
            raise RelevanceProviderError(
                "Vision relevance requires OPENAI_API_KEY. The key is read from the environment and is never logged."
            )
        started = time.perf_counter()
        with self._request_stats_lock:
            self._request_attempt_count = 0
            self._retry_count = 0
        judged: dict[int, dict] = {}
        completed: list[_BatchResult] = []
        errors: list[str] = []
        request_count = 0
        logger = _diagnostics_logger()

        for item in images:
            if _is_cancelled(cancelled):
                judged.setdefault(item.image_id, unknown_facts_record(item.image_id, "cancelled"))
                continue
            try:
                raw_batch, parsed = self._index_one(item)
                request_count += 1
                completed.append(raw_batch)
                record = parsed[0] if parsed else unknown_facts_record(item.image_id, "omitted")
                if record.get("unknown_reason"):
                    errors.append(
                        f"Vision API left image {item.image_id} unknown ({record.get('unknown_reason')})."
                    )
                judged[item.image_id] = record
            except (AiBudgetExceeded, AiProxyError):
                raise
            except Exception as exc:
                message = self._safe_error(exc)
                errors.append(message)
                logger.warning(
                    "image-facts failure reason=api_failure image_id=%s error=%s",
                    item.image_id, message,
                )
                judged[item.image_id] = unknown_facts_record(item.image_id, "api_failure")

        ordered = tuple(judged.get(item.image_id, unknown_facts_record(item.image_id, "unknown")) for item in images)
        failed_ids = tuple(int(item["image_id"]) for item in ordered if item.get("unknown_reason"))
        with self._request_stats_lock:
            request_attempt_count = self._request_attempt_count
            retry_count = self._retry_count
        return FactsRun(
            results=ordered,
            failed_image_ids=failed_ids,
            request_count=request_count,
            sent_image_count=sum(1 for item in ordered if not item.get("unknown_reason")),
            resize_seconds=sum(batch.resize_seconds for batch in completed),
            api_seconds=sum(batch.api_seconds for batch in completed),
            total_seconds=time.perf_counter() - started,
            retry_count=retry_count,
            request_attempt_count=request_attempt_count,
            input_tokens=sum(batch.input_tokens for batch in completed),
            output_tokens=sum(batch.output_tokens for batch in completed),
            errors=tuple(errors),
        )

    def _index_one(self, item: RelevanceImage) -> tuple[_BatchResult, tuple[dict, ...]]:
        resize_started = time.perf_counter()
        views = multiscale_views(item.path, max_edge=self.max_edge)
        resize_seconds = time.perf_counter() - resize_started
        content: list[dict] = [
            {
                "type": "text",
                "text": f"{FACTS_USER_PREFIX} image_id {item.image_id}.",
            }
        ]
        for label, data_url, _width, _height in views:
            content.append({"type": "text", "text": label})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url, "detail": self.image_detail},
                }
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "image_facts",
                    "strict": True,
                    "schema": fact_schema([item.image_id]),
                },
            },
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        diagnostics = (
            {
                "image_id": item.image_id,
                "view_count": len(views),
                "jpeg_width": views[0][2],
                "jpeg_height": views[0][3],
            },
        )
        api_started = time.perf_counter()
        if self._transport_via_legacy_post():
            response = self._post_with_retry(payload, image_diagnostics=diagnostics)
            api_seconds = time.perf_counter() - api_started
            try:
                raw_content = response["choices"][0]["message"]["content"]
                parsed_payload = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise RelevanceProviderError("Vision API returned an invalid structured result.") from exc
        else:
            check_ai_budget(
                AiRequestIntent(
                    operation=self.budget_operation,
                    kind=self.budget_kind,
                    model="",
                    request_count=1,
                )
            )
            proxy_views = []
            for label, data_url, _width, _height in views:
                encoded = data_url.split(",", 1)[-1] if "," in data_url else data_url
                proxy_views.append({"label": label, "image_jpeg_b64": encoded})
            envelope = invoke_ai_proxy(
                OPERATION_FACTS_GENERATE,
                {"image_id": item.image_id, "views": proxy_views},
            )
            api_seconds = time.perf_counter() - api_started
            parsed_payload = {"results": [envelope.result] if isinstance(envelope.result, dict) else []}
            response = {"usage": {}}
        results = parsed_payload.get("results") if isinstance(parsed_payload, dict) else None
        if not isinstance(results, list) or len(results) != 1:
            parsed = (unknown_facts_record(item.image_id, "malformed"),)
        else:
            record = dict(results[0])
            if int(record.get("image_id") or 0) != item.image_id:
                parsed = (unknown_facts_record(item.image_id, "malformed"),)
            else:
                record.pop("unknown_reason", None)
                record = prepare_facts_record(record)
                record["image_id"] = item.image_id
                parsed = (record,)
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        batch_result = _BatchResult(
            results=(),
            image_ids=(item.image_id,),
            resize_seconds=resize_seconds,
            api_seconds=api_seconds,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
        )
        return batch_result, parsed


def make_facts_provider() -> ImageFactsProvider:
    return ImageFactsProvider(
        max_edge=DEFAULT_MAX_EDGE,
        image_detail=DEFAULT_IMAGE_DETAIL,
        temperature=0,
        batch_size=1,
        unknown_retries=0,
        system_prompt=FACT_PROMPT,
        prompt_version=FACTS_PROMPT_VERSION,
        include_relevance_score=False,
    )
