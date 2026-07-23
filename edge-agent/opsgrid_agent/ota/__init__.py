"""OTA executors for signed configuration and agent artifacts."""

from opsgrid_agent.ota.agent_executor import (
    AgentSelfUpdateError,
    AgentSelfUpdateExecutor,
)
from opsgrid_agent.ota.executor import OTAUpdateError, OTAUpdateExecutor

__all__ = [
    "AgentSelfUpdateError",
    "AgentSelfUpdateExecutor",
    "OTAUpdateError",
    "OTAUpdateExecutor",
]
