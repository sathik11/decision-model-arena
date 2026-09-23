import os

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from pydantic import Field
from typing_extensions import Annotated

from asset_triage.orchestrator import TriageOrchestrator
from asset_triage.schemas import Incident

load_dotenv(override=False)


@tool(approval_mode="never_require")
async def triage_incident(
    incident_json: Annotated[
        str,
        Field(description="A JSON object containing an asset incident report and evidence."),
    ],
) -> str:
    """Classify and route an asset incident using a typed, confidence-aware decision engine."""
    incident = Incident.model_validate_json(incident_json)
    result = await TriageOrchestrator.from_environment().triage(incident)
    return result.model_dump_json(indent=2)


def main() -> None:
    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=DefaultAzureCredential(),
    )
    agent = Agent(
        client=client,
        instructions=(
            "You are an operations decision-support agent. Use triage_incident for every "
            "incident assessment. Explain the typed findings and missing evidence. Never "
            "claim an operational action was executed. Safety-critical, environmental, "
            "destructive, or low-confidence decisions require human approval. When asking "
            "the tool, pass valid JSON matching the user's incident."
        ),
        tools=[triage_incident],
        default_options={"store": False},
    )
    ResponsesHostServer(agent).run()


if __name__ == "__main__":
    main()
