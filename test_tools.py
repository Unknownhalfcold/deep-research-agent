from tools import tavily_search

result = tavily_search.invoke(
    {
        "query": "What is LangChain Deep Agents?",
        "max_results": 1,
    }
)

print(result[:2000])
