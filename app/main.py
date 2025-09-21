# app/main.py
import os
import time
import logging
import asyncio
from typing import Optional
from fastapi import FastAPI, Form, BackgroundTasks, Request
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client as TwilioClient

# Optional Redis (async)
try:
    import aioredis
    REDIS_AVAILABLE = True
except Exception:
    aioredis = None
    REDIS_AVAILABLE = False

# Import your bot classes from your repo
# Adjust import paths if files are in different modules
from app.voice2 import OptimizedVoiceAssistant  # existing in your codebase
from app.property_rag import RealEstateRAG        # existing in your codebase

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("realestate-bot")

app = FastAPI(title="RealEstate Voice Bot")

# Load env / config
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")  # Twilio phone number
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")  # e.g. https://realestate-bot-xxx.a.run.app

REDIS_URL = os.getenv("REDIS_URL")  # redis://user:pass@host:6379/0

# Twilio client (for outbound calls)
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Session storage: use redis when configured, fallback to in-memory dict (dev)
_sessions = {}  # in-memory fallback: {call_sid: {bot: OptimizedVoiceAssistant(...), start_time: ts}}

redis = None
if REDIS_URL:
    if not REDIS_AVAILABLE:
        logger.warning("REDIS_URL set but aioredis not installed. Install aioredis to use Redis.")
    else:
        # initialize redis client asynchronously on startup
        pass

# Shared resources preloaded (mimic your prewarm)
rag = RealEstateRAG()
logger.info("Loaded RealEstateRAG index.")
# Pre-warm Gemini usage if needed in your voice code (it's done inside your classes)

FALLBACK_REPLY = (
    "I'm still pulling up the latest details. Could you share a bit more while I check?"
)

# ---------- Helper functions ----------
async def get_session(call_sid: str):
    """Return session dict with 'bot' and 'start_time' keys."""
    if REDIS_URL and REDIS_AVAILABLE:
        key = f"call:{call_sid}"
        data = await redis.hgetall(key)
        if data:
            # store minimal session in memory referencing call_sid
            # We store only a marker in redis and keep actual bot in memory for now
            # (in production you'd store minimal state and rehydrate as needed)
            return _sessions.get(call_sid)
        return None
    else:
        return _sessions.get(call_sid)

async def set_session(call_sid: str, bot_obj):
    if REDIS_URL and REDIS_AVAILABLE:
        key = f"call:{call_sid}"
        await redis.hset(key, mapping={"created": str(time.time())})
        await redis.expire(key, 3600)  # 1 hour TTL
    _sessions[call_sid] = {"bot": bot_obj, "start_time": time.time()}

async def clear_session(call_sid: str):
    if REDIS_URL and REDIS_AVAILABLE:
        key = f"call:{call_sid}"
        await redis.delete(key)
    if call_sid in _sessions:
        try:
            del _sessions[call_sid]
        except KeyError:
            pass

def clean_text_for_tts(text: str) -> str:
    """Re-use the same cleaning function you had in your repo (shortened)."""
    # your repo has a more comprehensive version; call that if available.
    text = text.replace("AED", "Arab Emirates Dirham")
    text = text.replace("ROI", "return on investment")
    text = " ".join(text.split())
    return text

# ---------- FastAPI events ----------
@app.on_event("startup")
async def startup_event():
    global redis
    if REDIS_URL and REDIS_AVAILABLE:
        redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        logger.info("Connected to Redis.")
    else:
        if REDIS_URL and not REDIS_AVAILABLE:
            logger.warning("REDIS_URL set but aioredis not available; continuing with in-memory sessions.")
    logger.info("App startup complete.")

@app.on_event("shutdown")
async def shutdown_event():
    if redis:
        await redis.close()

# ---------- Request models ----------
class OutboundCallRequest(BaseModel):
    to_number: str
    client_name: Optional[str] = None
    property_id: Optional[str] = None

# ---------- Endpoints ----------
@app.post("/voice")
async def voice(CallSid: str = Form(...), From: str = Form(None), To: str = Form(None)):
    """
    Entry point for inbound calls. Twilio will POST here when a call is answered.
    We create a new bot session and return TwiML with a Gather to capture speech.
    """
    logger.info(f"Incoming call: CallSid={CallSid} From={From} To={To}")

    # Create bot session
    bot = OptimizedVoiceAssistant(CallSid)
    await set_session(CallSid, bot)

    # Compose greeting from your existing logic
    profit = bot.client_data['current_price'] - bot.client_data['bought_price']
    roi_percentage = (profit / bot.client_data['bought_price']) * 100
    greeting = (
        f"Hi {bot.client_data.get('name', '')}, I'm Alexa from Baaz Landmark Real Estate. "
        f"Your {bot.client_data.get('location', '')} property gained {profit:,} Arab Emirates Dirhams since {bot.client_data.get('purchase_year')} - "
        f"that's {roi_percentage:.1f} percent return on investment. Ready to discuss?"
    )
    resp = VoiceResponse()
    gather = Gather(input="speech", action="/process", timeout=4, speechTimeout="auto")
    gather.say(clean_text_for_tts(greeting), voice="alice")
    resp.append(gather)

    # Fallback if no speech
    resp.say("I didn't catch that. Goodbye!", voice="alice")
    resp.hangup()
    return Response(content=str(resp), media_type="application/xml")

@app.post("/process")
async def process(CallSid: str = Form(...), SpeechResult: str = Form(None), Confidence: str = Form(None)):
    """
    Process speech result from Twilio. Produce an immediate reply using your bot logic.
    Twilio will POST SpeechResult (if using <Gather input="speech">).
    """
    start_ts = time.time()
    logger.info(f"/process called for {CallSid} speech='{SpeechResult}'")

    sess = await get_session(CallSid)
    if not sess:
        # session expired or not found
        resp = VoiceResponse()
        resp.say("Session expired. Please call again or request a callback.", voice="alice")
        resp.hangup()
        return Response(content=str(resp), media_type="application/xml")

    bot: OptimizedVoiceAssistant = sess["bot"]

    user_input = (SpeechResult or "").strip().lower()
    if not user_input:
        resp = VoiceResponse()
        resp.say("Could you repeat that?", voice="alice")
        gather = Gather(input="speech", action="/process", timeout=4, speechTimeout="auto")
        gather.say("Please say that again.", voice="alice")
        resp.append(gather)
        return Response(content=str(resp), media_type="application/xml")

    # Use your bot's logic (handle_intents, generate_fast_response, RAG parallelism etc.)
    intent = bot.handle_intents(user_input)
    logger.info(f"Detected intent={intent}")

    # Quick-handled intents (mirror existing logic)
    resp = VoiceResponse()
    try:
        if intent == "strong_confirm":
            bot.confirm_count += 2
            reply = "Perfect! I'll prepare detailed ROI projections and our senior advisor will contact you within 24 hours. Goodbye!"
            resp.say(clean_text_for_tts(reply), voice="alice")
            resp.hangup()
            await clear_session(CallSid)
            return Response(content=str(resp), media_type="application/xml")

        if intent == "strong_reject":
            bot.reject_count += 2
            reply = "I understand. If anything changes, contact Baaz Landmark. Have a nice day!"
            resp.say(clean_text_for_tts(reply), voice="alice")
            resp.hangup()
            await clear_session(CallSid)
            return Response(content=str(resp), media_type="application/xml")

        # For other intents: follow original parallel pattern (RAG + response)
        # We'll do a short async wrapper to avoid blocking the webhook
        loop = asyncio.get_running_loop()
        # Run blocking functions in executor if they are CPU-bound or sync
        main_future = loop.run_in_executor(None, bot.generate_fast_response, user_input, intent)
        rag_future = loop.run_in_executor(
            None, lambda: rag.query_knowledge_base(user_input, k=1)
        )

        main_response = None
        rag_context = None

        try:
            main_response = await asyncio.wait_for(main_future, timeout=4.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout generating fast response for %s", CallSid)
            main_future.cancel()

        try:
            rag_context = await asyncio.wait_for(rag_future, timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout retrieving RAG context for %s", CallSid)
            rag_future.cancel()

        # Combine intelligently (similar to your original)
        if main_response:
            if rag_context and len(rag_context) > 0:
                reply = f"{main_response} {rag_context}"
            else:
                reply = main_response
        else:
            reply = FALLBACK_REPLY
            logger.info("Using fallback reply for %s after timeout", CallSid)

        if len(reply) > 300:
            reply = reply[:297] + "."

        resp.say(clean_text_for_tts(reply), voice="alice")

        # Continue conversation
        gather = Gather(input="speech", action="/process", timeout=4, speechTimeout="auto")
        gather.say("What are your thoughts?", voice="alice")
        resp.append(gather)

        elapsed = time.time() - start_ts
        logger.info(f"/process finished for {CallSid} in {elapsed:.2f}s")
        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        logger.exception("Error during /process handling")
        resp.say("Technical issue. Connecting you to an agent.", voice="alice")
        resp.hangup()
        await clear_session(CallSid)
        return Response(content=str(resp), media_type="application/xml")

@app.post("/outbound_call")
async def outbound_call(req: OutboundCallRequest, background_tasks: BackgroundTasks):
    """
    Initiate an outbound call (bot calls a person).
    The Twilio call will request PUBLIC_BASE_URL/voice as the TwiML endpoint.
    """
    if not twilio_client:
        return JSONResponse(status_code=500, content={"error": "Twilio not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN required)"})

    if not TWILIO_FROM_NUMBER or not PUBLIC_BASE_URL:
        return JSONResponse(status_code=400, content={"error": "TWILIO_FROM_NUMBER and PUBLIC_BASE_URL must be set"})

    to_number = req.to_number
    callback_url = f"{PUBLIC_BASE_URL}/voice"
    logger.info(f"Placing outbound call to {to_number}, TwiML URL: {callback_url}")

    try:
        call = twilio_client.calls.create(
            to=to_number,
            from_=TWILIO_FROM_NUMBER,
            url=callback_url,  # Twilio will GET this to get TwiML (we used POST in inbound; Twilio supports GET too)
            method="POST"
        )
        # Optionally store call.sid or kickoff background tasks
        return {"status": "initiated", "call_sid": call.sid}
    except Exception as e:
        logger.exception("Twilio outbound call failed")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/health")
async def health():
    return {"status": "healthy", "active_sessions": len(_sessions)}

