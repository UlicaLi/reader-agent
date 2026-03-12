# markdown_split_merge.py
from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain_core.documents import Document
from typing import Iterable, Dict, Any, Tuple, Generator


def chunk_markdown_pages(
    markdown_pages: Iterable[Dict[str, Any]], header_rules: list[Tuple[str, str]]
) -> Generator[Document, None, None]:
    """
    对多页 markdown 文本按 header_rules 分段，并跨页合并无 header 的段落。
    支持输入和输出均为生成器。
    Args:
        markdown_pages: 可迭代对象 [{"markdown": str, "pageIndex": int}, ...]
        header_rules: list [("#", "Header 1"), ("##", "Header 2"), ...]
    Yields:
        Document，每个 Document.metadata["pageIndex"] 为页码列表
    """
    splitter = MarkdownHeaderTextSplitter(header_rules)
    merged_docs = []
    for page_idx, markdown_page in enumerate(markdown_pages):
        split_docs = splitter.split_text(markdown_page["markdown"])
        # 跨页合并
        if page_idx > 0 and split_docs and not split_docs[0].metadata:
            if merged_docs:
                last_doc = merged_docs[-1]
                # 合并内容
                merged_content = (
                    last_doc.page_content + "\n" + split_docs[0].page_content
                )
                # 合并页码
                last_doc_pages = last_doc.metadata.get("pageIndex", [])
                if not isinstance(last_doc_pages, list):
                    last_doc_pages = [last_doc_pages]
                merged_pages = last_doc_pages + [markdown_page["pageIndex"]]
                # 合并 metadata
                merged_metadata = dict(last_doc.metadata)
                merged_metadata["pageIndex"] = merged_pages
                # 替换最后一个
                merged_docs[-1] = Document(
                    page_content=merged_content, metadata=merged_metadata
                )
            # 跳过第一个分段
            split_docs = split_docs[1:]
        # 追加本页分段
        for split_doc in split_docs:
            merged_metadata = dict(split_doc.metadata)
            # pageIndex 统一为列表
            merged_metadata["pageIndex"] = [markdown_page["pageIndex"]]
            merged_docs.append(
                Document(page_content=split_doc.page_content, metadata=merged_metadata)
            )
        # 每处理完一页就 yield 已合并的 doc（除了最后一个，可能还要继续合并）
        while len(merged_docs) > 1:
            yield merged_docs.pop(0)
    # 最后剩下的全部 yield
    for doc in merged_docs:
        yield doc


# 示例用法
if __name__ == "__main__":
    header_rules = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    markdown_pages = (
        {
            "markdown": "hi\n\n```markdown\n## in code\n\nin code hi\n```",
            "pageIndex": 0,
        },
        {"markdown": "## hello\n\nyour turn\n\n", "pageIndex": 1},
        {"markdown": "yes, my turn\n\n## next\n\n hahaha", "pageIndex": 2},
    )
    for doc in chunk_markdown_pages(markdown_pages, header_rules):
        print("===========================")
        print(doc)
        print("---------------------------\n\n")
