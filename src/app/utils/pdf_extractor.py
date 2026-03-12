import os
import fitz


class PDFExtractor:
    """PDF 提取器，用于将 PDF 页面转换为 PNG 图片

    支持两种使用方式：
    1. 使用 with 语句（推荐）：
       with PDFExtractor("file.pdf") as extractor:
           extractor.convert_all_pages_to_png("output/")

    2. 手动管理生命周期：
       extractor = PDFExtractor("file.pdf")
       extractor.open()
       extractor.convert_all_pages_to_png("output/")
       extractor.close()
    """

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = None
        self._opened_by_context = False

    def open(self):
        """打开 PDF 文档"""
        if self.doc is None:
            self.doc = fitz.open(self.pdf_path)
        return self

    def close(self):
        """关闭 PDF 文档"""
        if self.doc:
            self.doc.close()
            self.doc = None

    def __enter__(self):
        """进入 with 语句时自动打开文档"""
        self._opened_by_context = True
        return self.open()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出 with 语句时自动关闭文档"""
        if self._opened_by_context:
            self.close()
            self._opened_by_context = False

    def __del__(self):
        """析构函数，确保文档被关闭"""
        self.close()

    @property
    def page_count(self) -> int:
        """获取页面数量"""
        return len(self.doc)

    def convert_page_to_png(
        self, page_num: int, output_path: str, dpi: int = 72
    ) -> str:
        """将指定页面转换为 PNG 图片"""
        if not (0 <= page_num < self.page_count):
            raise ValueError(f"页面编号 {page_num} 超出范围 [0, {self.page_count-1}]")

        page = self.doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0))

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        pix.save(output_path)
        return output_path


if __name__ == "__main__":
    # 方式1：使用 with 语句（推荐）
    print("方式1：使用 with 语句")
    with PDFExtractor("test.pdf") as extractor:
        print(f"页面数量: {extractor.page_count}")
        extractor.convert_page_to_png(0, "output/page_001.png")

    print("\n方式2：手动管理生命周期")
    # 方式2：手动管理生命周期
    extractor = PDFExtractor("test.pdf")
    extractor.open()
    try:
        print(f"页面数量: {extractor.page_count}")
        # extractor.convert_all_pages_to_png("output2/")
    finally:
        extractor.close()
