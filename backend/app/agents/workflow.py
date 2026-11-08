r"""LangGraph orchestration of the processing pipeline.

    analyze -> extract -> validate --(garbled pages found, first time)--> ocr_retry -> validate
                                   \--(otherwise)--> chunk -> END

Progress is reported through config["configurable"]["progress"](stage, percent).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agents import chunk_manager, pdf_analyzer, text_extraction, text_validation


class WorkflowState(TypedDict, total=False):
    file_path: str
    analysis: dict
    pages: list[dict]
    retry_pages: list[int]
    ocr_retried: bool
    chunks: dict


def _progress(config: RunnableConfig) -> Callable[[str, float], None]:
    return (config or {}).get("configurable", {}).get("progress") or (lambda stage, pct: None)


def analyze_node(state: WorkflowState, config: RunnableConfig) -> dict:
    _progress(config)("analyzing", 2)
    analysis = pdf_analyzer.analyze_pdf(Path(state["file_path"]))
    return {"analysis": analysis, "ocr_retried": False}


def extract_node(state: WorkflowState, config: RunnableConfig) -> dict:
    progress = _progress(config)

    def cb(done: int, total: int) -> None:
        progress("extracting", 5 + 65 * done / max(total, 1))

    pages = text_extraction.extract_pages(Path(state["file_path"]), state["analysis"], progress=cb)
    return {"pages": pages}


def validate_node(state: WorkflowState, config: RunnableConfig) -> dict:
    _progress(config)("validating", 72)
    pages, retry = text_validation.validate_pages(state["pages"])
    return {"pages": pages, "retry_pages": retry}


def ocr_retry_node(state: WorkflowState, config: RunnableConfig) -> dict:
    _progress(config)("ocr_retry", 75)
    retry = set(state.get("retry_pages", []))
    redone = {p["page_number"]: p for p in text_extraction.extract_pages(
        Path(state["file_path"]), state["analysis"], force_ocr=retry, only_pages=retry)}
    pages = []
    for p in state["pages"]:
        new = redone.get(p["page_number"])
        if new and new["paragraphs"]:
            new["errors"] = []
            pages.append(new)
        else:
            pages.append(p)  # keep the original text if OCR produced nothing
    return {"pages": pages, "ocr_retried": True, "retry_pages": []}


def route_after_validate(state: WorkflowState) -> str:
    if state.get("retry_pages") and not state.get("ocr_retried"):
        return "ocr_retry"
    return "chunk"


def chunk_node(state: WorkflowState, config: RunnableConfig) -> dict:
    _progress(config)("chunking", 85)
    return {"chunks": chunk_manager.build_chunks(state["pages"])}


def build_workflow():
    g = StateGraph(WorkflowState)
    g.add_node("analyze", analyze_node)
    g.add_node("extract", extract_node)
    g.add_node("validate", validate_node)
    g.add_node("ocr_retry", ocr_retry_node)
    g.add_node("chunk", chunk_node)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "extract")
    g.add_edge("extract", "validate")
    g.add_conditional_edges("validate", route_after_validate, {"ocr_retry": "ocr_retry", "chunk": "chunk"})
    g.add_edge("ocr_retry", "validate")
    g.add_edge("chunk", END)
    return g.compile()


_compiled = None


def run_processing_workflow(file_path: Path, progress: Callable[[str, float], None] | None = None) -> WorkflowState:
    global _compiled
    if _compiled is None:
        _compiled = build_workflow()
    return _compiled.invoke(
        {"file_path": str(file_path)},
        config={"configurable": {"progress": progress}, "recursion_limit": 25},
    )
