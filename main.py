import sys

from dotenv import load_dotenv
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel
from tools import search_tool, wiki_tool, save_tool

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


class HealthResponse(BaseModel):
    topic: str
    summary: str
    Disease: str
    HealthStatus: str
    Habits: list[str]   



llm = ChatGroq(model="openai/gpt-oss-20b", max_tokens=2500, reasoning_effort="low", max_retries=1, timeout=20)
parser = PydanticOutputParser(pydantic_object=HealthResponse)

prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
            You are a health assistant that provides clear, practical, and
            evidence-based health information. Answer the user's health query
            directly, avoid diagnosing or prescribing treatment, and recommend
            consulting a qualified healthcare professional for serious or
            persistent symptoms. Use the available tools when useful. Return a
            clear plain-text answer after using the tools.
            """,
        ),
        ("placeholder", "{chat_history}"),
        ("human", "{query}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
)
tools = [search_tool, wiki_tool, save_tool]

agent = create_tool_calling_agent(
    llm=llm,
    prompt=prompt,
    tools=tools
)

agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
query = input("What can i help you research? ")
raw_response = agent_executor.invoke({"query": query})
print(raw_response)

formatter_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Convert the answer into the requested HealthResponse format. "
            "Return only valid structured output.\n{format_instructions}",
        ),
        ("human", "Question: {query}\nAnswer: {answer}"),
    ]
).partial(format_instructions=parser.get_format_instructions())

structured_response = (formatter_prompt | llm | parser).invoke(
    {"query": query, "answer": raw_response["output"]}
)
print(structured_response)
