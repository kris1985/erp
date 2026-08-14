#!/usr/bin/env python3
"""Register the workshop-agent LLM-as-a-Judge evaluator in LangSmith.

The script versions the Structured Prompt and then creates the offline evaluator.
The default is dry-run so this script cannot create remote resources by accident.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PROMPT_NAME = "workshop-agent-evidence-judge"


def build_structured_prompt():
    from langchain_core.prompts.structured import StructuredPrompt
    from pydantic import BaseModel, Field

    class JudgeResult(BaseModel):
        grounded: bool = Field(description="所有事实性结论都能由参考证据支持")
        decision_quality: str = Field(description="仅可为 pass、review 或 fail")
        concise: bool = Field(description="默认短答没有重复、长表或无关展开")
        reason: str = Field(description="最多 80 字，指出唯一最重要的问题")

    return StructuredPrompt.from_messages_and_schema(
        [
            (
                "system",
                "你是鞋厂 ERP 的严格质检员。根据问题、回答与参考证据评分。"
                "订单号、日期、数量、金额、产能、交期、质量风险等事实必须能在参考证据中逐项找到；"
                "无证据即 grounded=false 且 decision_quality=fail。"
                "用户没有要求详细时，重复解释、长表格、工具过程均 concise=false。"
                "建议可以是建议，但不得伪装成已确认事实。信息不足时明确说暂不能确认是正确行为。"
                "只返回符合 schema 的结果。",
            ),
            ("human", "问题：{question}\n\n回答：{answer}\n\n参考证据：{reference}"),
        ],
        schema=JudgeResult.model_json_schema(),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt-repo-handle",
        default=os.getenv("LANGSMITH_WORKSHOP_JUDGE_PROMPT", PROMPT_NAME),
        help="LangSmith Structured Prompt repo_handle (default: workshop-agent-evidence-judge)",
    )
    parser.add_argument(
        "--commit",
        default=os.getenv("LANGSMITH_WORKSHOP_JUDGE_COMMIT", "latest"),
        help="Prompt commit hash or tag (default: latest)",
    )
    parser.add_argument("--apply", action="store_true", help="Create the evaluator remotely")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    config = {
        "name": "Workshop Agent Evidence & Concision Judge",
        "type": "llm",
        "llm_evaluator": {
            "prompt_repo_handle": args.prompt_repo_handle,
            "commit_hash_or_tag": args.commit,
            "variable_mapping": {
                "question": "inputs.messages",
                "answer": "outputs.messages",
                "reference": "reference.evidence_ledger",
            },
            "use_corrections_dataset": True,
            "num_few_shot_examples": 3,
        },
    }
    if not args.apply:
        print("Dry run. This evaluator will be created with:")
        print(config)
        print("Re-run with --apply after setting LANGSMITH_API_KEY.")
        return

    from app.config import get_settings
    from langsmith import Client

    settings = get_settings()
    client = Client(
        api_key=settings.langsmith_api_key,
        api_url=settings.langsmith_endpoint,
    )
    try:
        prompt_url = client.push_prompt(args.prompt_repo_handle, object=build_structured_prompt())
        print(f"Versioned Structured Prompt: {prompt_url}")
    except Exception as exc:
        # LangSmith returns 409 when this exact Structured Prompt is already
        # the latest commit. That is success for an idempotent registration;
        # continue so a missing evaluator can still be created.
        if exc.__class__.__name__ != "LangSmithConflictError":
            raise
        print("Structured Prompt already matches latest commit.")
    created = await client.evaluators.create(**config)
    print(f"Created evaluator: {created.evaluator.id}")


if __name__ == "__main__":
    asyncio.run(main())
