"""Bright Smiles Dental voice agent pipeline.

Builds and runs the Pipecat pipeline:
  Transport In → Deepgram STT → User Aggregator → OpenAI LLM (w/ tools) →
  ElevenLabs TTS → Transport Out → Assistant Aggregator
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport

from server.tools import ALL_TOOLS, register_tools

# Load the system prompt from disk
_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.md"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


async def run_bot(
    transport: BaseTransport,
    *,
    handle_sigint: bool = False,
    call_sid: str | None = None,
) -> None:
    """Build and run the voice agent pipeline.

    Args:
        transport: A configured Pipecat transport (SmallWebRTC or FastAPIWebsocket).
        handle_sigint: Whether the runner should trap SIGINT.
        call_sid: Twilio Call SID for transfer support (None in browser mode).
    """
    logger.info("Building Bright Smiles Dental pipeline")

    # ---- Services ----
    stt = DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        settings=DeepgramSTTService.Settings(
            model="nova-3",
        ),
    )

    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(
            voice=os.environ["ELEVENLABS_VOICE_ID"],
            model=os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5"),
        ),
    )

    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(
            model="gpt-4o",
            system_instruction=SYSTEM_PROMPT,
        ),
    )

    # ---- Context & Aggregators ----
    context = LLMContext(tools=ALL_TOOLS)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    # ---- Pipeline ----
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # ---- Register tools (needs task reference for EndFrame) ----
    call_sid_holder: dict[str, str | None] = {"call_sid": call_sid}
    register_tools(llm, tts, task, call_sid_holder)

    # ---- Transport events ----
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected — starting conversation")
        # Add a developer message to trigger the greeting
        context.add_message(
            {
                "role": "developer",
                "content": (
                    "A caller just connected. Greet them with your standard greeting: "
                    '"Thanks for calling Bright Smiles Dental, this is Mia — how can I help?"'
                ),
            }
        )
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await task.cancel()

    # ---- Run ----
    runner = PipelineRunner(handle_sigint=handle_sigint)
    await runner.run(task)
