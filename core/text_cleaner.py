"""Text sanitization and cleaning utilities for LLM outputs and research data.
Removes thinking tokens (<think>), markdown wrapper fences, conversational preambles,
pleasantries/filler, and web scraper noise from generated responses.
"""
import re
from typing import List


def clean_llm_output(raw_text: str) -> str:
    """Thoroughly sanitize LLM generated technical reports to ensure clean, presentation-grade output."""
    if not raw_text or not raw_text.strip():
        return ""

    text = raw_text.strip()

    # 1. Strip reasoning / thinking tags (<think>...</think>, <thought>...</thought>, [THOUGHT]...[/THOUGHT])
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<thought>[\s\S]*?</thought>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[THOUGHT\][\s\S]*?\[/THOUGHT\]", "", text, flags=re.IGNORECASE)

    # If an unclosed <think> or <thought> tag exists at start, strip everything up to next major section or end
    if re.search(r"<(?:think|thought)>", text, flags=re.IGNORECASE) and not re.search(r"</(?:think|thought)>", text, flags=re.IGNORECASE):
        # Find if a markdown header starts after the unclosed tag
        header_match = re.search(r"\n+(#\s+[\s\S]*)", text)
        if header_match:
            text = header_match.group(1).strip()
        else:
            text = re.sub(r"^<(?:think|thought)>[\s\S]*", "", text, flags=re.IGNORECASE).strip()

    # 2. Strip XML wrapper tags like <answer>, <output>, <response>, <markdown>, <report>
    text = re.sub(r"</?(?:answer|output|response|result|report|final_answer|markdown)>\s*", "", text, flags=re.IGNORECASE)

    # 3. Strip leading codeblock fence if the entire text is wrapped in ```markdown ... ``` or ``` ... ```
    codeblock_full = re.match(r"^```(?:markdown|md|text)?\s*\n([\s\S]*?)\n```\s*$", text, flags=re.IGNORECASE)
    if codeblock_full:
        text = codeblock_full.group(1).strip()
    else:
        # If starts with ```markdown but no closing fence, or partial
        text = re.sub(r"^```(?:markdown|md|text)?\s*\n", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n```\s*$", "", text)

    # 4. Strip conversational preamble / filler from the start of the output
    preamble_patterns = [
        r"^(?:Here (?:is|are) (?:the|a|your|my) (?:comprehensive |final |detailed |exhaustive )?(?:research )?(?:report|analysis|summary|document|overview)[\s\S]*?:)\s*",
        r"^(?:Sure(?:thing)?[,!.]?\s*(?:(?:Here is|I have|below is|in this)[\s\S]*?:)?)\s*",
        r"^(?:Certainly(?:,!.)?\s*(?:(?:Here is|I have|below is|in this)[\s\S]*?:)?)\s*",
        r"^(?:Of course(?:,!.)?\s*(?:(?:Here is|I have|below is)[\s\S]*?:)?)\s*",
        r"^(?:Understood(?:,!.)?\s*(?:(?:Here is|I have|below is)[\s\S]*?:)?)\s*",
        r"^(?:Based on (?:the provided|the gathered|the indexed|your) (?:research|notes|sources|evidence|data|documents)[\s\S]*?:)\s*",
        r"^(?:In this (?:technical )?(?:report|analysis|document),? (?:we will|we examine|we provide|we explore)[\s\S]*?:)\s*",
        r"^(?:As an AI (?:research assistant|language model)[\s\S]*?:)\s*",
        r"^(?:Below is (?:the|a) (?:final |comprehensive |detailed )?(?:research )?report[\s\S]*?:)\s*",
        r"^(?:I have (?:thoroughly )?synthesized (?:the|your) (?:research|findings)[\s\S]*?:)\s*",
    ]
    for _ in range(5):
        prev_text = text
        for pattern in preamble_patterns:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
        if text == prev_text:
            break

    # 5. Strip conversational sign-offs, disclaimers, and trailing pleasantries
    postscript_patterns = [
        r"\n+(?:I hope this (?:(?:report|information|analysis) )?(?:helps|is useful|meets your expectations)[\s\S]*$)",
        r"\n+(?:Hope this (?:helps|is useful)[\s\S]*$)",
        r"\n+(?:Let me know if you (?:need|would like|require|have)[\s\S]*$)",
        r"\n+(?:Please let me know if (?:you need|there is)[\s\S]*$)",
        r"\n+(?:Feel free to ask (?:any )?(?:further|follow-up|more) questions[\s\S]*$)",
        r"\n+(?:If you have any (?:questions|further inquiries)[\s\S]*$)",
        r"\n+\*(?:Note|Disclaimer):[\s\S]*$",
        r"\n+\*\*(?:Note|Disclaimer):\*\*[\s\S]*$",
    ]
    for pattern in postscript_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # 6. Normalize headings (clean redundant bolding inside headers: e.g. ## **1. Executive Summary** -> ## 1. Executive Summary)
    cleaned_lines: List[str] = []
    for line in text.splitlines():
        # Match markdown headers with inner **...** bold markers
        header_bold_match = re.match(r"^(#{1,6}\s+)\*\*(.*?)\*\*:?$", line)
        if header_bold_match:
            cleaned_lines.append(f"{header_bold_match.group(1)}{header_bold_match.group(2).strip()}")
        else:
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # 7. Fix duplicate top `# Title`
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].startswith("# ") and lines[1] == "" and lines[2].startswith("# "):
        lines.pop(0)
        lines.pop(0)
        text = "\n".join(lines)

    # 8. Normalize excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text


def clean_qa_response(raw_text: str) -> str:
    """Sanitize interactive follow-up Q&A responses for direct, presentation-grade clarity."""
    if not raw_text or not raw_text.strip():
        return ""

    text = raw_text.strip()

    # 1. Strip reasoning tags
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<thought>[\s\S]*?</thought>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[THOUGHT\][\s\S]*?\[/THOUGHT\]", "", text, flags=re.IGNORECASE)

    # Unclosed thinking tags
    if re.search(r"<(?:think|thought)>", text, flags=re.IGNORECASE) and not re.search(r"</(?:think|thought)>", text, flags=re.IGNORECASE):
        text = re.sub(r"^<(?:think|thought)>[\s\S]*", "", text, flags=re.IGNORECASE).strip()

    # 2. Strip XML wrapper tags
    text = re.sub(r"</?(?:answer|output|response|result|final_answer)>\s*", "", text, flags=re.IGNORECASE)

    # 3. Strip outer codeblock fences if wrapped completely
    codeblock_full = re.match(r"^```(?:markdown|md|text)?\s*\n([\s\S]*?)\n```\s*$", text, flags=re.IGNORECASE)
    if codeblock_full:
        text = codeblock_full.group(1).strip()

    # 4. Strip conversational preambles
    qa_preambles = [
        r"^(?:Based on the (?:provided|available|verified|indexed) (?:context|evidence|sources|notes|documents)[\s\S]*?:)\s*",
        r"^(?:According to the (?:provided|available|verified) (?:context|evidence|sources)[\s\S]*?:)\s*",
        r"^(?:Based on the (?:provided|available|verified|indexed) (?:context|evidence|sources|notes|documents),?\s*)",
        r"^(?:According to the (?:provided|available|verified) (?:context|evidence|sources),?\s*)",
        r"^(?:Sure[,!]?\s*(?:(?:here is|to answer)[\s\S]*?:)?)\s*",
        r"^(?:Certainly[,!]?\s*(?:(?:here is|to answer)[\s\S]*?:)?)\s*",
        r"^(?:To answer your question:?\s*)",
        r"^(?:In response to your query:?\s*)",
        r"^(?:Regarding (?:the|your) (?:question|query) (?:about|regarding):?\s*)",
        r"^(?:Here (?:is|are) (?:the|a) (?:summary|breakdown|answer):?\s*)",
    ]
    for _ in range(5):
        prev_text = text
        for pattern in qa_preambles:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
        if text == prev_text:
            break

    # 5. Strip trailing pleasantries
    qa_postscripts = [
        r"\n+(?:I hope this (?:helps|answers your question)[\s\S]*$)",
        r"\n+(?:Let me know if you (?:need|have) (?:more|any) (?:details|questions)[\s\S]*$)",
        r"\n+(?:Feel free to ask (?:any )?(?:further|follow-up) questions[\s\S]*$)",
    ]
    for pattern in qa_postscripts:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sanitize_search_snippet(raw_text: str) -> str:
    """Scrub web scraper snippet dates, robot verification notices, and navigation debris."""
    if not raw_text or not raw_text.strip():
        return ""

    text = " ".join(raw_text.split()).strip()

    # Strip search snippet date prefixes: e.g. "Nov 14, 2026 ·", "3 days ago —", "August 2026 -"
    text = re.sub(r"^[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\s*[·\-–—|]\s*", "", text).strip()
    text = re.sub(r"^\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}\s*[·\-–—|]\s*", "", text).strip()
    text = re.sub(r"^\d+\s+(?:days?|hours?|weeks?|months?)\s+ago\s*[·\-–—|]\s*", "", text, flags=re.IGNORECASE).strip()
    # Strip dangling list prefixes from HTML/Markdown bullets
    text = re.sub(r"^[\-\*•]+\s+", "", text).strip()

    # Filter bot / robot alerts
    bot_terms = [
        "javascript is disabled",
        "verify that you're not a robot",
        "verify you are human",
        "enable javascript to run this app",
        "cookie preferences",
        "all rights reserved",
        "terms of use",
    ]
    for term in bot_terms:
        if term in text.lower():
            text = re.sub(re.escape(term), "", text, flags=re.IGNORECASE)

    # Strip trailing ellipses or incomplete crumbs
    text = re.sub(r"\s+\.\.\.$", "", text)
    return text.strip()
