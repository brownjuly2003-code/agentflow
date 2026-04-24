# AgentFlow Integrations

Install the published integrations package:

```bash
pip install agentflow-integrations
```

If you are working from this monorepo, use a local editable install instead:

```bash
python -m pip install -e "./integrations"
```

## LangChain

```python
from agentflow_integrations.langchain import AgentFlowToolkit
from langchain.agents import initialize_agent

toolkit = AgentFlowToolkit("http://localhost:8000", api_key="af-dev-key")
agent = initialize_agent(
    toolkit.get_tools(),
    llm,
    agent="zero-shot-react-description",
)

agent.run("What's the revenue for today?")
```

## LlamaIndex

```python
from agentflow_integrations.llamaindex import AgentFlowReader
from llama_index.core import VectorStoreIndex

reader = AgentFlowReader("http://localhost:8000", api_key="af-dev-key")
documents = reader.load_data(
    entity_type="order",
    metric_names=["revenue", "order_count"],
    window="24h",
)

index = VectorStoreIndex.from_documents(documents)
query_engine = index.as_query_engine()
query_engine.query("Which orders need attention?")
```

## CrewAI

Install CrewAI dependencies alongside the integrations package:

```bash
pip install agentflow-integrations
pip install crewai crewai-tools
```

```python
from crewai import Agent, Crew, Task

from agentflow_integrations.crewai import get_agentflow_tools

tools = get_agentflow_tools("http://localhost:8000", api_key="af-dev-key")

support_agent = Agent(
    role="Customer Support Specialist",
    goal="Answer customer questions about orders using real-time data",
    backstory="You help support teams resolve order questions with live platform data.",
    tools=tools,
)

task = Task(
    description="Explain the current status of order ORD-1 and report the latest revenue metric.",
    expected_output="A short support-ready answer with order status and revenue context.",
    agent=support_agent,
)

crew = Crew(
    agents=[support_agent],
    tasks=[task],
)

result = crew.kickoff()
print(result)
```
