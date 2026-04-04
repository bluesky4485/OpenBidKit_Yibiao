"""提示词构建工具。"""

from typing import Any, Dict, List


def read_expand_outline_prompt() -> str:
    """从简版技术方案中提取目录的系统提示词。"""
    return """你是一个专业的标书编写专家。请严格基于用户提交的标书技术方案原文完成目录提取任务。

要求：
1. 目录结构要全面覆盖技术标的所有必要目录，包含多级目录
2. 如果技术方案中有章节名称，则直接使用技术方案中的章节名称
3. 如果技术方案中没有章节名称，则结合全文，总结出章节名称
4. 返回标准 JSON 格式，包含章节编号、标题、描述和子章节，注意编号要连贯
5. 除了 JSON 结果外，不要输出任何其他内容

JSON 格式要求：
{
  "outline": [
    {
      "id": "1",
      "title": "",
      "description": "",
      "children": [
        {
          "id": "1.1",
          "title": "",
          "description": "",
          "children": [
            {
              "id": "1.1.1",
              "title": "",
              "description": ""
            }
          ]
        }
      ]
    }
  ]
}
"""


def _build_outline_system_prompt() -> str:
    """构建目录生成的共享系统提示词。"""
    return """你是一个专业的标书编写专家。根据提供的项目概述和技术评分要求，生成投标文件中技术标部分的目录结构。
如果用户提供了自己编写的目录，你要保证目录满足技术评分要求，并充分结合用户自己编写的目录。

要求：
1. 目录结构要全面覆盖技术标的所有必要章节
2. 章节名称要专业、准确，符合投标文件规范
3. 一级目录名称要与技术评分要求中的章节名称一致；如果技术评分要求中没有明确章节名称，则结合内容总结一级目录名称
4. 一共包括三级目录
5. 返回标准 JSON 格式，包含章节编号、标题、描述和子章节
6. 除了 JSON 结果外，不要输出任何其他内容

JSON 格式要求：
{
  "outline": [
    {
      "id": "1",
      "title": "",
      "description": "",
      "children": [
        {
          "id": "1.1",
          "title": "",
          "description": "",
          "children": [
            {
              "id": "1.1.1",
              "title": "",
              "description": ""
            }
          ]
        }
      ]
    }
  ]
}
"""


def _build_top_level_outline_system_prompt() -> str:
    """构建仅生成一级目录的系统提示词。"""
    return """你是一个专业的标书编写专家。根据提供的项目概述和技术评分要求，生成投标文件中技术标部分的一级目录结构。
如果用户提供了自己编写的目录，你要保证一级目录满足技术评分要求，并充分结合用户自己编写的目录。

要求：
1. 只生成一级目录，不要生成二级和三级目录
2. 一级目录名称要专业、准确，符合投标文件规范
3. 一级目录名称要尽量与技术评分要求中的章节名称一致；如果技术评分要求中没有明确章节名称，则结合内容总结一级目录名称
4. 返回标准 JSON 格式，使用 outline 字段，每个一级目录必须包含 id、title、description
5. 除了 JSON 结果外，不要输出任何其他内容

JSON 格式要求：
{
  "outline": [
    {
      "id": "1",
      "title": "",
      "description": ""
    }
  ]
}
"""


def _format_revision_suggestions(suggestions: list[str] | None) -> str:
    """格式化目录修正建议。"""
    if not suggestions:
        return ""

    suggestion_lines = [
        f"{index}. {item}" for index, item in enumerate(suggestions, start=1)
    ]
    return "\n\n本轮修正建议：\n" + "\n".join(suggestion_lines)


def generate_outline_prompt(
    overview: str,
    requirements: str,
    suggestions: list[str] | None = None,
) -> List[Dict[str, str]]:
    """生成标准目录的提示词。"""
    return [
        {"role": "system", "content": _build_outline_system_prompt()},
        {"role": "user", "content": f"项目概述：\n{overview}"},
        {"role": "user", "content": f"技术评分要求：\n{requirements}"},
        {
            "role": "user",
            "content": "请生成完整的技术标目录结构，确保覆盖所有技术评分要点。"
            + _format_revision_suggestions(suggestions),
        },
    ]


def generate_outline_with_old_prompt(
    overview: str,
    requirements: str,
    old_outline: str | None,
    suggestions: list[str] | None = None,
) -> List[Dict[str, str]]:
    """生成基于旧目录扩写的提示词。"""
    return [
        {"role": "system", "content": _build_outline_system_prompt()},
        {"role": "user", "content": f"项目概述：\n{overview}"},
        {"role": "user", "content": f"技术评分要求：\n{requirements}"},
        {"role": "user", "content": f"用户自己编写的目录：\n{old_outline or ''}"},
        {
            "role": "user",
            "content": "请在满足技术评分要求的前提下，充分结合用户自己编写的目录，生成完整的技术标目录结构。"
            + _format_revision_suggestions(suggestions),
        },
    ]


def generate_top_level_outline_prompt(
    overview: str,
    requirements: str,
    suggestions: list[str] | None = None,
) -> List[Dict[str, str]]:
    """生成仅包含一级目录的提示词。"""
    return [
        {"role": "system", "content": _build_top_level_outline_system_prompt()},
        {"role": "user", "content": f"项目概述：\n{overview}"},
        {"role": "user", "content": f"技术评分要求：\n{requirements}"},
        {
            "role": "user",
            "content": "请仅生成一级目录列表，不要生成二级和三级目录。返回的 JSON 仍然使用 outline 字段，每个一级目录都必须包含 id、title、description。"
            + _format_revision_suggestions(suggestions),
        },
    ]


def generate_top_level_outline_with_old_prompt(
    overview: str,
    requirements: str,
    old_outline: str | None,
    suggestions: list[str] | None = None,
) -> List[Dict[str, str]]:
    """生成结合旧目录的一级目录提示词。"""
    return [
        {"role": "system", "content": _build_top_level_outline_system_prompt()},
        {"role": "user", "content": f"项目概述：\n{overview}"},
        {"role": "user", "content": f"技术评分要求：\n{requirements}"},
        {"role": "user", "content": f"用户自己编写的目录：\n{old_outline or ''}"},
        {
            "role": "user",
            "content": "请在满足技术评分要求的前提下，充分结合用户自己编写的目录，仅生成一级目录，不要生成二级和三级目录。返回的 JSON 使用 outline 字段，每个一级目录都必须包含 id、title、description。"
            + _format_revision_suggestions(suggestions),
        },
    ]


def generate_children_outline_prompt(
    overview: str,
    requirements: str,
    parent_item: Dict[str, Any],
    suggestions: list[str] | None = None,
) -> List[Dict[str, str]]:
    """为指定一级目录生成二三级目录。"""
    parent_id = parent_item.get("id", "1")
    parent_title = parent_item.get("title", "未命名一级目录")
    parent_description = parent_item.get("description", "")

    system_prompt = """你是一个专业的标书编写专家。请围绕指定的一级目录，生成其下属的二级目录和三级目录。

要求：
1. 只输出当前一级目录下的二级和三级目录，不要重复输出一级目录本身
2. 返回标准 JSON，格式为 {"children": [...]} 
3. children 中只能包含当前一级目录的直接子目录，每个节点必须包含 id、title、description
4. 二级目录下如有三级目录，同样使用 children 字段
5. 章节编号必须以给定的一级目录编号为前缀，例如父级是 2，则二级目录编号从 2.1 开始，三级目录编号从 2.1.1 开始
6. 除了 JSON 结果外，不要输出任何其他内容
"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"项目概述：\n{overview}"},
        {"role": "user", "content": f"技术评分要求：\n{requirements}"},
        {
            "role": "user",
            "content": f"当前一级目录：\n编号：{parent_id}\n标题：{parent_title}\n描述：{parent_description}",
        },
        {
            "role": "user",
            "content": '请仅生成该一级目录下的二级、三级目录，返回格式必须是 {"children": [...]}。'
            + _format_revision_suggestions(suggestions),
        },
    ]


def generate_children_outline_with_old_prompt(
    overview: str,
    requirements: str,
    parent_item: Dict[str, Any],
    old_outline: str | None,
    suggestions: list[str] | None = None,
) -> List[Dict[str, str]]:
    """为指定一级目录生成二三级目录，并结合旧目录参考。"""
    messages = generate_children_outline_prompt(
        overview=overview,
        requirements=requirements,
        parent_item=parent_item,
        suggestions=suggestions,
    )
    messages.insert(
        4, {"role": "user", "content": f"用户自己编写的目录：\n{old_outline or ''}"}
    )
    messages[-1] = {
        "role": "user",
        "content": '请在满足技术评分要求的前提下，充分结合用户自己编写的目录，仅生成该一级目录下的二级、三级目录，返回格式必须是 {"children": [...]}。'
        + _format_revision_suggestions(suggestions),
    }
    return messages


def review_outline_messages(
    overview: str,
    requirements: str,
    outline_json: str,
) -> List[Dict[str, str]]:
    """构建目录审核消息。"""
    system_prompt = """你是一个严格的招标文件目录审核专家。请审核目录是否符合项目概述和技术评分要求。

要求：
1. 重点检查目录是否完整覆盖技术评分要点
2. 检查一级目录名称是否专业、准确，是否尽量与评分项原文保持一致
3. 检查目录层级是否清晰，是否达到三级目录要求，是否存在明显遗漏、错位、重复或不合理章节
4. 只返回 JSON，格式为：{"passed": true, "suggestions": []}
5. 若不通过，suggestions 中必须给出具体、可执行的修改建议
6. 除了 JSON 外，不要输出任何其他内容
"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"项目概述：\n{overview}"},
        {"role": "user", "content": f"技术评分要求：\n{requirements}"},
        {"role": "user", "content": f"待审核目录 JSON：\n{outline_json}"},
        {
            "role": "user",
            "content": "请判断该目录是否满足要求。若满足则返回 passed=true；若不满足则返回 passed=false，并给出具体修改建议。",
        },
    ]


def build_json_repair_messages(
    invalid_content: str,
    issues: list[str],
    target_description: str,
) -> List[Dict[str, str]]:
    """构建 JSON 定向修复消息。"""
    issue_lines = [f"{index}. {item}" for index, item in enumerate(issues, start=1)]

    system_prompt = """你是一个严格的 JSON 修复助手。请根据给出的原始内容和校验问题，修复现有结果。

要求：
1. 优先在原结果基础上做最小必要修改，不要整体重写
2. 尽量保留原有结构、字段值、节点顺序和已生成内容
3. 若缺少必填字段，应结合现有上下文补齐合理内容，不要用空字符串敷衍
4. 若存在多余说明、代码块包裹、字段名错误、children 结构不规范或顶层包裹错误，应修正为合法 JSON
5. 只返回修复后的完整 JSON，不要输出任何解释
"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"目标结果类型：{target_description}"},
        {"role": "user", "content": "当前校验问题：\n" + "\n".join(issue_lines)},
        {
            "role": "user",
            "content": f"待修复内容：\n```json\n{invalid_content}\n```",
        },
        {
            "role": "user",
            "content": "请在保留原有正确内容的前提下，仅修复上述问题，并返回完整 JSON。",
        },
    ]


def build_analysis_messages(
    file_content: str, analysis_type: str
) -> List[Dict[str, str]]:
    """构建文档分析消息。"""
    system_prompt = """你是一名专业的招标文件分析助手。请严格基于用户提供的招标文件原文完成分析任务。

通用要求：
1. 保持提取信息的全面性和准确性，尽量使用原文内容，不要自行编造
2. 只输出最终分析结果，不要输出额外说明、过程、提示语或客套话
3. 如果文档内容不足以支持某项结论，应明确说明原文未提及，不要凭空补充
"""

    file_prompt = f"""以下是完整招标文件全文，请先完整阅读，并仅基于原文完成后续任务：

{file_content}"""

    if analysis_type == "overview":
        task_prompt = """任务：提取并总结项目概述信息。

请重点关注以下方面：
1. 项目名称和基本信息
2. 项目背景和目的
3. 项目规模和预算
4. 项目时间安排
5. 项目要实施的具体内容
6. 主要技术特点
7. 其他关键要求

工作要求：
1. 保持提取信息的全面性和准确性，尽量使用原文内容，不要自己编写
2. 只关注与项目实施有关的内容，不提取商务信息
3. 直接返回整理好的项目概述，除此之外不返回任何其他内容
"""
    else:
        task_prompt = """任务：提取技术评分要求。

你是一名专业的招标文件分析师，擅长从复杂的招标文档中高效提取“技术评分项”相关内容。请严格按照以下步骤和规则执行任务：
### 1. 目标定位
- 重点识别文档中与“技术评分”、“评标方法”、“评分标准”、“技术参数”、“技术要求”、“技术方案”、“技术部分”或“评审要素”相关的章节（如“第X章 评标方法”或“附件X：技术评分表”）。
- 一定不要提取商务、价格、资质等与技术类评分项无关的条目。
### 2. 提取内容要求
对每一项技术评分项，按以下结构化格式输出（若信息缺失，标注“未提及”），如果评分项不够明确，你需要根据上下文分析并也整理成如下格式：
【评分项名称】：<原文描述，保留专业术语>
【权重/分值】：<具体分值或占比，如“30分”或“40%”>
【评分标准】：<详细规则，如“≥95%得满分，每低1%扣0.5分”>
【数据来源】：<文档中的位置，如“第5.2.3条”或“附件3-表2”>

### 3. 处理规则
- 模糊表述：有些招标文件格式不是很标准，没有明确的“技术评分表”，但一定都会有“技术评分”相关内容，请根据上下文判断评分项。
- 表格处理：若评分项以表格形式呈现，按行提取，并标注“[表格数据]”。
- 分层结构：若存在二级评分项（如“技术方案→子项1、子项2”），用缩进或编号体现层级关系。
- 单位统一：将所有分值统一为“分”或“%”，并注明原文单位。

### 4. 验证步骤
提取完成后，执行以下自检：
- [ ] 所有技术评分项是否覆盖（无遗漏）？
- [ ] 是否错误提取商务、价格、资质等与技术类评分项无关的条目？
- [ ] 权重总和是否与文档声明的技术分总分一致（如“技术部分共60分”）？

直接返回提取结果，除此之外不输出任何其他内容
"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": file_prompt},
        {"role": "user", "content": task_prompt},
    ]


def build_chapter_content_messages(
    chapter: Dict[str, Any],
    parent_chapters: List[Dict[str, Any]] | None = None,
    sibling_chapters: List[Dict[str, Any]] | None = None,
    project_overview: str = "",
) -> List[Dict[str, str]]:
    """构建章节正文生成消息。"""
    chapter_id = chapter.get("id", "unknown")
    chapter_title = chapter.get("title", "未命名章节")
    chapter_description = chapter.get("description", "")

    system_prompt = """你是一个专业的标书编写专家，负责为投标文件的技术标部分生成具体内容。

要求：
1. 内容要专业、准确，与章节标题和描述保持一致。
2. 这是技术方案，不是宣传报告，注意朴实无华，不要假大空。
3. 语言要正式、规范，符合标书写作要求，但不要使用奇怪的连接词，不要让人觉得内容像是 AI 生成的。
4. 内容要详细具体，避免空泛的描述。
5. 注意避免与同级章节内容重复，保持内容的独特性和互补性。
6. 直接返回章节内容，不生成标题，不要任何额外说明或格式标记。
"""

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    if project_overview.strip():
        messages.append(
            {"role": "user", "content": f"项目概述信息：\n{project_overview}"}
        )

    if parent_chapters:
        parent_lines = ["上级章节信息："]
        for parent in parent_chapters:
            parent_lines.append(
                f"- {parent.get('id', 'unknown')} {parent.get('title', '未命名章节')}\n  {parent.get('description', '')}"
            )
        messages.append({"role": "user", "content": "\n".join(parent_lines)})

    if sibling_chapters:
        sibling_lines = ["同级章节信息（请避免内容重复）："]
        for sibling in sibling_chapters:
            if sibling.get("id") == chapter_id:
                continue
            sibling_lines.append(
                f"- {sibling.get('id', 'unknown')} {sibling.get('title', '未命名章节')}\n  {sibling.get('description', '')}"
            )
        if len(sibling_lines) > 1:
            messages.append({"role": "user", "content": "\n".join(sibling_lines)})

    messages.append(
        {
            "role": "user",
            "content": f"""请为以下标书章节生成具体内容：

当前章节信息：
章节ID: {chapter_id}
章节标题: {chapter_title}
章节描述: {chapter_description}

请根据项目概述信息和上述章节层级关系，生成详细的专业内容，确保与上级章节的内容逻辑相承，同时避免与同级章节内容重复，突出本章节的独特性和技术方案优势。""",
        }
    )

    return messages


def build_expand_outline_messages(file_content: str) -> List[Dict[str, str]]:
    """构建方案扩写目录提取消息。"""
    return [
        {"role": "system", "content": read_expand_outline_prompt()},
        {
            "role": "user",
            "content": f"以下是完整技术方案全文，请先完整阅读，并仅基于原文完成后续任务：\n\n{file_content}",
        },
        {
            "role": "user",
            "content": "请从上述技术方案中提取完整目录结构，确保覆盖技术标的所有必要目录，并按要求返回标准 JSON。",
        },
    ]
