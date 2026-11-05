from datetime import datetime
from pathlib import Path

from langchain_community.tools import DuckDuckGoSearchRun, WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_core.tools import tool


_web_search = DuckDuckGoSearchRun()
_wikipedia_search = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())


@tool
def search_tool(query: str) -> str:
    """Search the web for information related to the user's query."""
    return _web_search.invoke(query)


@tool
def wiki_tool(query: str) -> str:
    """Search Wikipedia for background information."""
    return _wikipedia_search.invoke(query)


@tool
def save_tool(text: str) -> str:
    """Append research text to the local research output file."""
    output_path = Path(__file__).with_name("research_output.txt")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with output_path.open("a", encoding="utf-8") as output_file:
        output_file.write(
            f"--- Research Output ---\n"
            f"Timestamp: {timestamp}\n\n"
            f"{text}\n\n"
        )
    return f"Saved research to {output_path}"




