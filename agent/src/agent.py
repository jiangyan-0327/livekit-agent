import asyncio
import time
import httpx
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli, llm
from livekit.agents.types import ATTRIBUTE_AGENT_STATE
from livekit.agents.voice import room_io
from livekit.plugins import cartesia, deepgram, openai

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
LOCAL_ENV_PATH = Path(__file__).resolve().parents[1] / ".env.local"

load_dotenv(ROOT_ENV_PATH, override=False)
load_dotenv(LOCAL_ENV_PATH, override=True)

AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "echuu-voice-agent")

TTS_MODEL = os.getenv("ECHUU_AGENT_TTS_MODEL", "sonic-3")
TTS_VOICE = os.getenv(
    "ECHUU_AGENT_TTS_VOICE",
    "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
)
TTS_LANGUAGE = os.getenv("ECHUU_AGENT_TTS_LANGUAGE", "zh")
TTS_ENABLED = os.getenv("ECHUU_AGENT_TTS_ENABLED", "true").lower() == "true"

STT_MODEL = os.getenv("ECHUU_AGENT_STT_MODEL", "nova-3")
STT_LANGUAGE = os.getenv("ECHUU_AGENT_STT_LANGUAGE", "zh-CN")

LLM_MODEL = os.getenv("ECHUU_AGENT_LLM_MODEL", "glm-5.1")
LLM_BASE_URL = os.getenv(
    "ECHUU_AGENT_LLM_BASE_URL",
    "https://open.bigmodel.cn/api/paas/v4/",
)
LLM_API_KEY = os.getenv("ZAI_API_KEY", "")
LLM_TEMPERATURE = float(os.getenv("ECHUU_AGENT_LLM_TEMPERATURE", "0.7"))
LLM_MAX_TOKENS = int(os.getenv("ECHUU_AGENT_LLM_MAX_TOKENS", "200"))

CHAT_TOPIC = "lk.chat"

AGENT_STATE_LISTENING = "listening"
AGENT_STATE_THINKING = "thinking"
AGENT_STATE_SPEAKING = "speaking"

MAX_INPUT_CHARS = 500

VOICE_INPUT_COOLDOWN_SECONDS = 2.0
VOICE_DUPLICATE_WINDOW_SECONDS = 3.0

_last_voice_transcript_text = ""
_last_voice_transcript_at = 0.0


class EchuuAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You are Echuu's chat and TTS test agent.")


server = AgentServer()
_active_tasks: set[asyncio.Task] = set()
_message_lock = asyncio.Lock()

zhipu_llm = openai.LLM(
    model=LLM_MODEL,
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    temperature=LLM_TEMPERATURE,
    max_completion_tokens=LLM_MAX_TOKENS,
    timeout=httpx.Timeout(30.0),
)


async def set_agent_state(room, state: str) -> None:
    await room.local_participant.set_attributes(
        {
            ATTRIBUTE_AGENT_STATE: state,
        }
    )


async def send_agent_text(room, text: str, reply_to_id: str | None = None) -> None:
    await room.local_participant.send_text(
        text,
        topic=CHAT_TOPIC,
        reply_to_id=reply_to_id,
    )


async def read_text_stream(reader) -> str:
    chunks: list[str] = []

    async for chunk in reader:
        if isinstance(chunk, str):
            chunks.append(chunk)
        else:
            text = getattr(chunk, "text", None)
            if text:
                chunks.append(text)

    return "".join(chunks).strip()


def build_reply_text(text: str) -> str:
    return "我现在回复有点慢，请再试一次。"


async def generate_reply_text(text: str) -> str:
    if not LLM_API_KEY:
        return build_reply_text(text)

    chat_ctx = llm.ChatContext()
    chat_ctx.add_message(
        role="system",
        content=(
            "你是 Echuu 的中文语音助手。"
            "请用简短、自然、口语化的中文回答。"
            "不要使用 markdown，不要使用列表，不要输出太长。"
        ),
    )
    chat_ctx.add_message(role="user", content=text)

    response = await zhipu_llm.chat(chat_ctx=chat_ctx).collect()
    reply_text = response.text.strip()

    return reply_text or build_reply_text(text)


def _track_task(task: asyncio.Task) -> None:
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)


async def handle_user_transcript(room, session, ev) -> None:
    global _last_voice_transcript_text, _last_voice_transcript_at

    text = ev.transcript.strip()
    if not text or not ev.is_final:
        return

    now = time.time()

    # Cooldown: ignore any new voice input that lands too soon after the last one.
    if now - _last_voice_transcript_at < VOICE_INPUT_COOLDOWN_SECONDS:
        return

    # De-duplicate repeated final transcripts from the same utterance.
    if (
            text == _last_voice_transcript_text
            and now - _last_voice_transcript_at < VOICE_DUPLICATE_WINDOW_SECONDS
    ):
        return

    _last_voice_transcript_text = text
    _last_voice_transcript_at = now

    speaker = ev.speaker_id or "voice-user"

    await handle_user_text(room, session, speaker, text)


async def handle_user_text(room, session, sender_identity: str, text: str) -> None:
    text = text.strip()
    if not text:
        return

    async with _message_lock:
        await set_agent_state(room, AGENT_STATE_THINKING)

        try:
            try:
                reply_text = await generate_reply_text(text)
            except Exception as exc:
                print(f"[agent] llm failed: {exc}")
                reply_text = build_reply_text(text)

            await send_agent_text(room, reply_text)

            if TTS_ENABLED and session.tts is not None:
                try:
                    await set_agent_state(room, AGENT_STATE_SPEAKING)
                    print("[agent] starting tts playout")
                    speech = session.say(reply_text)
                    await speech.wait_for_playout()
                    print("[agent] finished tts playout")
                except Exception as exc:
                    print(f"[agent] tts failed: {exc}")
        finally:
            await set_agent_state(room, AGENT_STATE_LISTENING)


def register_stt_handlers(room, session) -> None:
    @session.on("user_input_transcribed")
    def on_user_input_transcribed(ev) -> None:
        _track_task(asyncio.create_task(handle_user_transcript(room, session, ev)))


def register_text_handlers(room, session) -> None:
    async def handle_text_stream(reader, participant_identity: str) -> None:
        if participant_identity == room.local_participant.identity:
            return

        text = await read_text_stream(reader)
        if not text:
            return

        await handle_user_text(room, session, participant_identity, text)

    def on_text_stream(reader, participant_identity: str) -> None:
        _track_task(asyncio.create_task(handle_text_stream(reader, participant_identity)))

    room.register_text_stream_handler(CHAT_TOPIC, on_text_stream)


@server.rtc_session(agent_name=AGENT_NAME)
async def echuu_voice_agent(ctx: JobContext) -> None:
    session = AgentSession(
        stt=deepgram.STT(
            model=STT_MODEL,
            language=STT_LANGUAGE,
        ),
        tts=cartesia.TTS(
            model=TTS_MODEL.removeprefix("cartesia/"),
            voice=TTS_VOICE,
            language=TTS_LANGUAGE,
        ) if TTS_ENABLED else None
    )

    await session.start(
        agent=EchuuAssistant(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            text_input=False,
            close_on_disconnect=False,
        ),
    )

    if session.room_io.subscribed_fut is not None:
        await session.room_io.subscribed_fut

    register_text_handlers(ctx.room, session)
    register_stt_handlers(ctx.room, session)
    await set_agent_state(ctx.room, AGENT_STATE_LISTENING)

    await asyncio.Future()


if __name__ == "__main__":
    cli.run_app(server)
