"""OpenAI 服务。"""

import json
import logging
import uuid
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List

import openai
from pydantic import BaseModel, ValidationError

from ..config import settings
from ..models.schemas import (
    OutlineChildrenResponse,
    OutlineResponse,
    OutlineReviewResponse,
)
from ..utils import prompt_manager
from ..utils.config_manager import config_manager
from ..utils.errors import AppError

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]]
JsonValidator = Callable[[Dict[str, Any]], None]


class OpenAIService:
    """封装 OpenAI 模型调用与标书相关生成逻辑。"""

    def __init__(self):
        config = config_manager.load_config()
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "")
        self.model_name = config.get("model_name", "gpt-3.5-turbo")
        if not self.api_key:
            raise AppError("请先配置OpenAI API密钥", status_code=400)
        self.client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
        )

    def _chat_endpoint_url(self) -> str:
        """获取聊天完成接口地址。"""
        base_url = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        return f"{base_url}/chat/completions"

    def _log_ai_request(
        self,
        request_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        response_format: dict | None,
    ) -> None:
        """记录 AI 请求日志。"""
        if not settings.enable_file_logging:
            return

        logger.debug(
            "AI_REQUEST %s",
            json.dumps(
                {
                    "request_id": request_id,
                    "url": self._chat_endpoint_url(),
                    "model": self.model_name,
                    "temperature": temperature,
                    "response_format": response_format,
                    "messages": messages,
                },
                ensure_ascii=False,
            ),
        )

    def _log_ai_response(self, request_id: str, content: str) -> None:
        """记录 AI 响应日志。"""
        if not settings.enable_file_logging:
            return

        logger.debug(
            "AI_RESPONSE %s",
            json.dumps(
                {
                    "request_id": request_id,
                    "url": self._chat_endpoint_url(),
                    "model": self.model_name,
                    "content": content,
                },
                ensure_ascii=False,
            ),
        )

    def _log_ai_raw_response(
        self,
        request_id: str,
        raw_chunks: list[dict[str, Any]],
        content: str,
    ) -> None:
        """记录 AI 接口原始响应日志。"""
        if not settings.enable_file_logging:
            return

        logger.debug(
            "AI_RAW_RESPONSE %s",
            json.dumps(
                {
                    "request_id": request_id,
                    "url": self._chat_endpoint_url(),
                    "model": self.model_name,
                    "raw_chunks": raw_chunks,
                    "content": content,
                },
                ensure_ascii=False,
                default=str,
            ),
        )

    def _log_ai_error(
        self,
        request_id: str,
        messages: list[dict[str, str]],
        temperature: float,
        response_format: dict | None,
        partial_content: str,
        raw_chunks: list[dict[str, Any]],
        error: Exception,
    ) -> None:
        """记录 AI 异常日志。"""
        if not settings.enable_file_logging:
            return

        logger.debug(
            "AI_ERROR %s",
            json.dumps(
                {
                    "request_id": request_id,
                    "url": self._chat_endpoint_url(),
                    "model": self.model_name,
                    "temperature": temperature,
                    "response_format": response_format,
                    "messages": messages,
                    "partial_content": partial_content,
                    "raw_chunks": raw_chunks,
                    "error": str(error),
                },
                ensure_ascii=False,
                default=str,
            ),
        )

    @staticmethod
    def _dump_chunk(chunk: Any) -> dict[str, Any]:
        """序列化 OpenAI SDK 返回的 chunk。"""
        if hasattr(chunk, "model_dump"):
            return chunk.model_dump(mode="json")
        return {"raw": str(chunk)}

    @staticmethod
    def _extract_json_content(content: str) -> str:
        """提取模型响应中的 JSON 内容，兼容 Markdown 代码块包裹。"""
        normalized = content.strip()
        if not normalized.startswith("```"):
            return normalized

        lines = normalized.splitlines()
        if not lines:
            return normalized

        first_line = lines[0].strip().lower()
        last_line = lines[-1].strip()
        if not last_line.startswith("```"):
            return normalized

        if first_line in {"```", "```json", "```javascript", "```js"}:
            return "\n".join(lines[1:-1]).strip()

        return normalized

    @staticmethod
    def _is_response_format_unsupported_error(message: str) -> bool:
        """判断当前错误是否表示模型不支持 response_format。"""
        normalized = message.lower()
        if "response_format" not in normalized:
            return False

        return any(
            marker in normalized
            for marker in (
                "not supported",
                "does not support",
                "not support",
                "unsupported",
                "unknown parameter",
                "invalid parameter",
            )
        )

    @staticmethod
    async def _emit_progress(
        progress_callback: ProgressCallback | None,
        message: str,
    ) -> None:
        """发送目录生成过程进度。"""
        if progress_callback is None:
            return

        await progress_callback(message)

    async def get_available_models(self) -> List[str]:
        """获取可用模型列表。"""
        try:
            models = await self.client.models.list()
        except Exception as exc:
            raise AppError(f"获取模型列表失败: {exc}", status_code=502) from exc

        chat_models: list[str] = []
        for model in models.data:
            model_id = model.id.lower()
            if any(
                keyword in model_id
                for keyword in ["gpt", "claude", "chat", "llama", "qwen", "deepseek"]
            ):
                chat_models.append(model.id)
        return sorted(set(chat_models))

    async def stream_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        response_format: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        """流式调用聊天完成接口。"""
        request_id = uuid.uuid4().hex
        parts: list[str] = []
        raw_chunks: list[dict[str, Any]] = []
        self._log_ai_request(request_id, messages, temperature, response_format)

        try:
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                stream=True,
                **(
                    {"response_format": response_format}
                    if response_format is not None
                    else {}
                ),
            )
        except Exception as exc:
            self._log_ai_error(
                request_id,
                messages,
                temperature,
                response_format,
                "",
                raw_chunks,
                exc,
            )
            raise AppError(f"模型调用失败: {exc}", status_code=502) from exc

        try:
            async for chunk in stream:
                raw_chunks.append(self._dump_chunk(chunk))
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content is not None:
                    parts.append(content)
                    yield content
        except Exception as exc:
            self._log_ai_error(
                request_id,
                messages,
                temperature,
                response_format,
                "".join(parts),
                raw_chunks,
                exc,
            )
            raise AppError(f"模型调用失败: {exc}", status_code=502) from exc

        self._log_ai_response(request_id, "".join(parts))
        self._log_ai_raw_response(request_id, raw_chunks, "".join(parts))

    async def collect_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        response_format: dict | None = None,
    ) -> str:
        """收集流式输出并拼接为完整文本。"""
        parts: list[str] = []
        async for chunk in self.stream_chat_completion(
            messages,
            temperature=temperature,
            response_format=response_format,
        ):
            parts.append(chunk)
        return "".join(parts)

    async def _collect_chat_completion_with_json_mode_fallback(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        use_response_format: bool,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[str, bool]:
        """优先使用 JSON 模式请求，不支持时自动降级为普通请求。"""
        try:
            content = await self.collect_chat_completion(
                messages,
                temperature=temperature,
                response_format={"type": "json_object"}
                if use_response_format
                else None,
            )
            return content, use_response_format
        except AppError as exc:
            if (
                not use_response_format
                or not self._is_response_format_unsupported_error(exc.message)
            ):
                raise

            await self._emit_progress(
                progress_callback,
                "当前模型不支持结构化 JSON 响应，已降级为普通请求解析。",
            )
            content = await self.collect_chat_completion(
                messages,
                temperature=temperature,
                response_format=None,
            )
            return content, False

    @staticmethod
    def _normalize_json_response(
        content: str,
        schema: type[BaseModel] | None = None,
        validator: JsonValidator | None = None,
    ) -> Dict[str, Any]:
        """解析、校验并标准化 JSON 响应。"""
        json_content = OpenAIService._extract_json_content(content)
        parsed = json.loads(json_content)

        if schema is None:
            normalized = parsed
        else:
            validated = schema.model_validate(parsed)
            normalized = validated.model_dump(exclude_none=True)

        if validator is not None:
            validator(normalized)

        return normalized

    @staticmethod
    def _format_json_issues(error: Exception) -> list[str]:
        """格式化 JSON 解析或校验问题。"""
        if isinstance(error, json.JSONDecodeError):
            return [
                f"JSON 语法错误：第 {error.lineno} 行第 {error.colno} 列附近 {error.msg}。"
            ]

        if isinstance(error, ValidationError):
            issues: list[str] = []
            for item in error.errors():
                location = ".".join(str(part) for part in item.get("loc", [])) or "root"
                message = item.get("msg", "字段校验失败")
                issues.append(f"{location}: {message}")
            return issues or [str(error)]

        return [str(error)]

    async def _repair_json_response(
        self,
        invalid_content: str,
        issues: list[str],
        temperature: float,
        use_response_format: bool,
        progress_callback: ProgressCallback | None,
        progress_label: str,
    ) -> tuple[str, bool]:
        """基于当前结果发起一次定向 JSON 修复。"""
        await self._emit_progress(
            progress_callback,
            f"{progress_label}格式校验失败，正在基于当前结果进行修复。",
        )
        repair_messages = prompt_manager.build_json_repair_messages(
            invalid_content=invalid_content,
            issues=issues,
            target_description=progress_label,
        )
        return await self._collect_chat_completion_with_json_mode_fallback(
            messages=repair_messages,
            temperature=temperature,
            use_response_format=use_response_format,
            progress_callback=progress_callback,
        )

    async def generate_outline(
        self,
        overview: str,
        requirements: str,
        uploaded_expand: bool = False,
        old_outline: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> Dict[str, Any]:
        """生成目录结构。"""
        return await self._generate_outline_workflow(
            overview=overview,
            requirements=requirements,
            uploaded_expand=uploaded_expand,
            old_outline=old_outline,
            progress_callback=progress_callback,
        )

    async def generate_expand_outline(self, file_content: str) -> Dict[str, Any]:
        """从已有技术方案中提取目录结构。"""
        return await self._collect_json_response(
            messages=prompt_manager.build_expand_outline_messages(file_content),
            temperature=0.7,
            schema=OutlineResponse,
        )

    async def stream_chapter_content(
        self,
        chapter: Dict[str, Any],
        parent_chapters: list[dict[str, Any]] | None = None,
        sibling_chapters: list[dict[str, Any]] | None = None,
        project_overview: str = "",
    ) -> AsyncGenerator[str, None]:
        """流式生成单章节内容。"""
        messages = prompt_manager.build_chapter_content_messages(
            chapter=chapter,
            parent_chapters=parent_chapters,
            sibling_chapters=sibling_chapters,
            project_overview=project_overview,
        )
        async for chunk in self.stream_chat_completion(messages, temperature=0.7):
            yield chunk

    async def generate_chapter_content(
        self,
        chapter: Dict[str, Any],
        parent_chapters: list[dict[str, Any]] | None = None,
        sibling_chapters: list[dict[str, Any]] | None = None,
        project_overview: str = "",
    ) -> str:
        """生成单章节完整正文。"""
        return await self.collect_chat_completion(
            prompt_manager.build_chapter_content_messages(
                chapter=chapter,
                parent_chapters=parent_chapters,
                sibling_chapters=sibling_chapters,
                project_overview=project_overview,
            ),
            temperature=0.7,
        )

    async def _collect_json_response(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        schema: type[BaseModel] | None = None,
        validator: JsonValidator | None = None,
        progress_callback: ProgressCallback | None = None,
        progress_label: str = "JSON结果",
        failure_message: str = "模型返回的 JSON 数据格式无效",
    ) -> Dict[str, Any]:
        """收集并校验 JSON 响应。"""
        max_retries = 2
        total_attempts = max_retries + 1
        use_response_format = True

        for attempt in range(total_attempts):
            try:
                (
                    content,
                    use_response_format,
                ) = await self._collect_chat_completion_with_json_mode_fallback(
                    messages=messages,
                    temperature=temperature,
                    use_response_format=use_response_format,
                    progress_callback=progress_callback,
                )
                normalized = self._normalize_json_response(
                    content,
                    schema=schema,
                    validator=validator,
                )
                return normalized
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                issues = self._format_json_issues(exc)
                logger.warning(
                    "模型返回非法 JSON，第 %s/%s 次尝试: %s；问题: %s",
                    attempt + 1,
                    total_attempts,
                    content,
                    " | ".join(issues),
                )

                try:
                    (
                        repaired_content,
                        use_response_format,
                    ) = await self._repair_json_response(
                        invalid_content=content,
                        issues=issues,
                        temperature=temperature,
                        use_response_format=use_response_format,
                        progress_callback=progress_callback,
                        progress_label=progress_label,
                    )
                    normalized = self._normalize_json_response(
                        repaired_content,
                        schema=schema,
                        validator=validator,
                    )
                    return normalized
                except AppError as repair_error:
                    logger.warning(
                        "JSON 修复请求失败，第 %s/%s 次尝试: %s",
                        attempt + 1,
                        total_attempts,
                        repair_error.message,
                    )
                    exc = repair_error
                except (
                    json.JSONDecodeError,
                    ValidationError,
                    ValueError,
                ) as repair_error:
                    logger.warning(
                        "JSON 修复后仍校验失败，第 %s/%s 次尝试: %s；问题: %s",
                        attempt + 1,
                        total_attempts,
                        repaired_content,
                        " | ".join(self._format_json_issues(repair_error)),
                    )
                    exc = repair_error

                if attempt == max_retries:
                    await self._emit_progress(
                        progress_callback,
                        f"{progress_label}连续 {total_attempts} 次校验失败。",
                    )
                    raise AppError(failure_message, status_code=502) from exc

                await self._emit_progress(
                    progress_callback,
                    f"{progress_label}第 {attempt + 1}/{total_attempts} 次校验失败，正在重试。",
                )

        raise AppError(failure_message, status_code=502)

    async def _generate_outline_workflow(
        self,
        overview: str,
        requirements: str,
        uploaded_expand: bool,
        old_outline: str | None,
        progress_callback: ProgressCallback | None = None,
    ) -> Dict[str, Any]:
        """执行目录生成、审核与回退工作流。"""
        await self._emit_progress(progress_callback, "开始生成目录结构。")
        first_outline, generation_mode = await self._generate_outline_by_mode(
            overview=overview,
            requirements=requirements,
            uploaded_expand=uploaded_expand,
            old_outline=old_outline,
            mode="auto",
            progress_callback=progress_callback,
        )

        await self._emit_progress(
            progress_callback, "首次目录生成完成，开始审核目录质量。"
        )
        first_review = await self._review_outline(
            overview=overview,
            requirements=requirements,
            outline=first_outline,
            progress_callback=progress_callback,
            stage_label="首次审核",
        )
        if first_review["passed"]:
            await self._emit_progress(progress_callback, "目录审核通过，准备返回结果。")
            return first_outline

        suggestions = first_review.get("suggestions") or [
            "请根据项目概述和技术评分要求补全目录覆盖范围，并修正不合理章节。"
        ]
        await self._emit_progress(
            progress_callback,
            "目录审核未通过，正在根据修改建议重新生成。",
        )

        try:
            second_outline, _ = await self._generate_outline_by_mode(
                overview=overview,
                requirements=requirements,
                uploaded_expand=uploaded_expand,
                old_outline=old_outline,
                mode=generation_mode,
                progress_callback=progress_callback,
                suggestions=suggestions,
            )
        except AppError:
            await self._emit_progress(
                progress_callback,
                "根据审核建议重新生成失败，已回退到首次生成结果。",
            )
            return first_outline

        await self._emit_progress(progress_callback, "二次生成完成，开始最终审核。")
        second_review = await self._review_outline(
            overview=overview,
            requirements=requirements,
            outline=second_outline,
            progress_callback=progress_callback,
            stage_label="最终审核",
        )
        if second_review["passed"]:
            await self._emit_progress(
                progress_callback, "最终审核通过，准备返回修正后的结果。"
            )
        else:
            await self._emit_progress(
                progress_callback,
                "最终审核未完全通过，已返回修正后的第二次结果。",
            )

        return second_outline

    async def _generate_outline_by_mode(
        self,
        overview: str,
        requirements: str,
        uploaded_expand: bool,
        old_outline: str | None,
        mode: str,
        progress_callback: ProgressCallback | None = None,
        suggestions: list[str] | None = None,
    ) -> tuple[Dict[str, Any], str]:
        """根据指定模式生成目录。"""
        if mode == "full":
            outline = await self._generate_outline_full(
                overview=overview,
                requirements=requirements,
                uploaded_expand=uploaded_expand,
                old_outline=old_outline,
                suggestions=suggestions,
                progress_callback=progress_callback,
            )
            return outline, "full"

        if mode == "fallback":
            outline = await self._generate_outline_fallback(
                overview=overview,
                requirements=requirements,
                uploaded_expand=uploaded_expand,
                old_outline=old_outline,
                suggestions=suggestions,
                progress_callback=progress_callback,
            )
            return outline, "fallback"

        try:
            outline = await self._generate_outline_full(
                overview=overview,
                requirements=requirements,
                uploaded_expand=uploaded_expand,
                old_outline=old_outline,
                suggestions=suggestions,
                progress_callback=progress_callback,
            )
            return outline, "full"
        except AppError as exc:
            if exc.message != "模型返回的目录数据格式无效":
                raise
            await self._emit_progress(
                progress_callback,
                "一次性生成完整目录失败，切换为分步生成模式。",
            )
            outline = await self._generate_outline_fallback(
                overview=overview,
                requirements=requirements,
                uploaded_expand=uploaded_expand,
                old_outline=old_outline,
                suggestions=suggestions,
                progress_callback=progress_callback,
            )
            return outline, "fallback"

    async def _generate_outline_full(
        self,
        overview: str,
        requirements: str,
        uploaded_expand: bool,
        old_outline: str | None,
        suggestions: list[str] | None,
        progress_callback: ProgressCallback | None,
    ) -> Dict[str, Any]:
        """一次性生成完整目录。"""
        await self._emit_progress(progress_callback, "正在一次性生成完整目录。")
        if uploaded_expand:
            messages = prompt_manager.generate_outline_with_old_prompt(
                overview,
                requirements,
                old_outline,
                suggestions=suggestions,
            )
        else:
            messages = prompt_manager.generate_outline_prompt(
                overview,
                requirements,
                suggestions=suggestions,
            )

        return await self._collect_json_response(
            messages=messages,
            temperature=0.7,
            schema=OutlineResponse,
            validator=self._validate_complete_outline,
            progress_callback=progress_callback,
            progress_label="完整目录",
            failure_message="模型返回的目录数据格式无效",
        )

    async def _generate_outline_fallback(
        self,
        overview: str,
        requirements: str,
        uploaded_expand: bool,
        old_outline: str | None,
        suggestions: list[str] | None,
        progress_callback: ProgressCallback | None,
    ) -> Dict[str, Any]:
        """分步生成目录：先一级目录，再逐个生成二三级目录。"""
        await self._emit_progress(
            progress_callback, "正在分步生成目录，先生成一级目录。"
        )
        top_level_outline = await self._generate_top_level_outline(
            overview=overview,
            requirements=requirements,
            uploaded_expand=uploaded_expand,
            old_outline=old_outline,
            suggestions=suggestions,
            progress_callback=progress_callback,
        )

        top_level_items = top_level_outline.get("outline", [])
        assembled_items: list[dict[str, Any]] = []
        for index, item in enumerate(top_level_items, start=1):
            await self._emit_progress(
                progress_callback,
                f"正在生成第 {index}/{len(top_level_items)} 个一级目录的二三级目录：{item.get('title', '未命名章节')}。",
            )
            merged_item = {
                "id": item.get("id", str(index)),
                "title": item.get("title", "未命名章节"),
                "description": item.get("description", ""),
            }
            children_response = await self._generate_outline_children(
                overview=overview,
                requirements=requirements,
                parent_item=item,
                uploaded_expand=uploaded_expand,
                old_outline=old_outline,
                suggestions=suggestions,
                progress_callback=progress_callback,
            )
            children = children_response.get("children") or []
            if children:
                merged_item["children"] = children
            assembled_items.append(merged_item)

        outline = self._renumber_outline({"outline": assembled_items})
        validated = OutlineResponse.model_validate(outline)
        normalized = validated.model_dump(exclude_none=True)
        self._validate_complete_outline(normalized)
        return normalized

    async def _generate_top_level_outline(
        self,
        overview: str,
        requirements: str,
        uploaded_expand: bool,
        old_outline: str | None,
        suggestions: list[str] | None,
        progress_callback: ProgressCallback | None,
    ) -> Dict[str, Any]:
        """生成一级目录。"""
        if uploaded_expand:
            messages = prompt_manager.generate_top_level_outline_with_old_prompt(
                overview=overview,
                requirements=requirements,
                old_outline=old_outline,
                suggestions=suggestions,
            )
        else:
            messages = prompt_manager.generate_top_level_outline_prompt(
                overview=overview,
                requirements=requirements,
                suggestions=suggestions,
            )

        return await self._collect_json_response(
            messages=messages,
            temperature=0.7,
            schema=OutlineResponse,
            validator=self._validate_top_level_outline,
            progress_callback=progress_callback,
            progress_label="一级目录",
            failure_message="模型返回的目录数据格式无效",
        )

    async def _generate_outline_children(
        self,
        overview: str,
        requirements: str,
        parent_item: Dict[str, Any],
        uploaded_expand: bool,
        old_outline: str | None,
        suggestions: list[str] | None,
        progress_callback: ProgressCallback | None,
    ) -> Dict[str, Any]:
        """生成某个一级目录下的二三级目录。"""
        if uploaded_expand:
            messages = prompt_manager.generate_children_outline_with_old_prompt(
                overview=overview,
                requirements=requirements,
                parent_item=parent_item,
                old_outline=old_outline,
                suggestions=suggestions,
            )
        else:
            messages = prompt_manager.generate_children_outline_prompt(
                overview=overview,
                requirements=requirements,
                parent_item=parent_item,
                suggestions=suggestions,
            )

        return await self._collect_json_response(
            messages=messages,
            temperature=0.7,
            schema=OutlineChildrenResponse,
            validator=self._validate_children_outline,
            progress_callback=progress_callback,
            progress_label=f"章节 {parent_item.get('title', '未命名章节')} 子目录",
            failure_message="模型返回的目录数据格式无效",
        )

    async def _review_outline(
        self,
        overview: str,
        requirements: str,
        outline: Dict[str, Any],
        progress_callback: ProgressCallback | None,
        stage_label: str,
    ) -> Dict[str, Any]:
        """审核目录是否符合招标要求。"""
        messages = prompt_manager.review_outline_messages(
            overview=overview,
            requirements=requirements,
            outline_json=json.dumps(outline, ensure_ascii=False),
        )
        return await self._collect_json_response(
            messages=messages,
            temperature=0.3,
            schema=OutlineReviewResponse,
            progress_callback=progress_callback,
            progress_label=stage_label,
            failure_message="模型返回的审核结果格式无效",
        )

    @classmethod
    def _renumber_outline(cls, outline: Dict[str, Any]) -> Dict[str, Any]:
        """统一重排目录编号，避免分步生成时编号错乱。"""
        return {"outline": cls._renumber_items(outline.get("outline", []))}

    @classmethod
    def _renumber_items(
        cls,
        items: list[dict[str, Any]],
        parent_prefix: str = "",
    ) -> list[dict[str, Any]]:
        """递归重排目录项编号。"""
        normalized_items: list[dict[str, Any]] = []
        for index, item in enumerate(items, start=1):
            item_id = f"{parent_prefix}.{index}" if parent_prefix else str(index)
            normalized_item = {**item, "id": item_id}
            children = item.get("children") or []
            if children:
                normalized_item["children"] = cls._renumber_items(children, item_id)
            else:
                normalized_item.pop("children", None)
            normalized_items.append(normalized_item)

        return normalized_items

    @staticmethod
    def _outline_depth(items: list[dict[str, Any]]) -> int:
        """计算目录的最大层级深度。"""
        if not items:
            return 0

        return 1 + max(
            OpenAIService._outline_depth(item.get("children") or []) for item in items
        )

    @classmethod
    def _validate_complete_outline(cls, payload: Dict[str, Any]) -> None:
        """校验完整目录至少达到三级结构。"""
        outline = payload.get("outline") or []
        if not outline:
            raise ValueError("目录不能为空")

        if cls._outline_depth(outline) < 3:
            raise ValueError("完整目录至少需要三级结构")

    @staticmethod
    def _validate_top_level_outline(payload: Dict[str, Any]) -> None:
        """校验一级目录结果非空。"""
        outline = payload.get("outline") or []
        if not outline:
            raise ValueError("一级目录不能为空")

    @classmethod
    def _validate_children_outline(cls, payload: Dict[str, Any]) -> None:
        """校验一级目录下至少生成出二级目录。"""
        children = payload.get("children") or []
        if not children:
            raise ValueError("二级目录不能为空")
