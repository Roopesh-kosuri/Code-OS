import { useState, useEffect } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownPreview({ content }: { content: string }) {
  const [debouncedContent, setDebouncedContent] = useState(content);

  // Debounce live markdown re-render at 300ms
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedContent(content);
    }, 300);
    return () => clearTimeout(handler);
  }, [content]);

  return (
    <div
      data-testid="markdown-preview-pane"
      className="h-full w-full overflow-auto bg-[#0d0e12] p-6 text-on-surface select-text font-ui-label-reg leading-relaxed"
    >
      <div className="max-w-4xl mx-auto prose prose-invert prose-headings:font-bold prose-headings:tracking-tight prose-a:text-primary prose-code:text-primary-fixed prose-pre:bg-surface-container-low prose-pre:border prose-pre:border-outline-variant/30 prose-table:border-collapse prose-th:border prose-th:border-outline-variant/30 prose-th:p-2 prose-td:border prose-td:border-outline-variant/30 prose-td:p-2">
        {/* Default react-markdown sanitizes raw HTML tags and does NOT execute script tags */}
        <Markdown remarkPlugins={[remarkGfm]}>
          {debouncedContent}
        </Markdown>
      </div>
    </div>
  );
}
