/**
 * Universal marker sanitization for all agent display surfaces (Phase 10.19 Part B).
 * Used across Rony chat, Agent Console Live Logs, Steering Chat, and team logs.
 *
 * Strips:
 * - [PROPOSAL: ...], <<<<, ====, >>>>
 * - [TOOL_CALL: ...], [/TOOL_CALL]
 * - [DONE]
 * - Leaked model control tokens (<|im_start|>, <|end|>, etc.)
 */

const SANITIZER_PATTERNS: RegExp[] = [
  /\[PROPOSAL:\s*[^\]]+\][\s\S]*?(?:>{2,}|(?=\[(?:PROPOSAL|TOOL_CALL)|$))/gi,
  /\[TOOL_CALL:\s*[\w-]+\][\s\S]*?(?:\[\/TOOL_CALL\]|(?=\[(?:PROPOSAL|TOOL_CALL)|$))/gi,
  /\[\/TOOL_CALL\]/gi,
  /<{4,}\s*(?:ORIGINAL)?/gi,
  /={4,}/gi,
  />{4,}/gi,
  /\[DONE\]/gi,
  /<\|(?:im_start|im_end|start|end|pad|eot|fim_prefix|fim_suffix|fim_middle).*?\|>/gi,
  /<\|(?:start|to=).*?>/gi,
];

export function sanitizeDisplayText(text: string | null | undefined): string {
  if (!text || typeof text !== 'string') {
    return '';
  }

  let cleaned = text;
  for (const pattern of SANITIZER_PATTERNS) {
    cleaned = cleaned.replace(pattern, '');
  }

  cleaned = cleaned.replace(/\n{3,}/g, '\n\n');
  return cleaned.trim();
}
