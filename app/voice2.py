# app/voice2.py
import logging

logger = logging.getLogger("voice2")

class OptimizedVoiceAssistant:
    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self.confirm_count = 0
        self.reject_count = 0

        # For now, mock client data (later you can fetch from DB or RAG)
        self.client_data = {
            "name": "Client",
            "location": "Dubai",
            "purchase_year": 2018,
            "bought_price": 1000000,
            "current_price": 1400000,
        }

    def handle_intents(self, text: str) -> str:
        """Very basic intent detection. Expand later with NLP if needed."""
        text = text.lower()

        if any(word in text for word in ["yes", "okay", "interested", "sure", "agree"]):
            return "strong_confirm"
        if any(word in text for word in ["no", "not interested", "stop", "never", "leave me"]):
            return "strong_reject"

        return "neutral"

    def generate_fast_response(self, user_input: str, intent: str) -> str:
        """Generate quick reply (short sentences, friendly tone)."""
        if intent == "neutral":
            return f"Thanks for sharing. Could you tell me more about your preferences in {self.client_data['location']}?"
        elif intent == "strong_confirm":
            return "Perfect. I’ll prepare the next steps right away."
        elif intent == "strong_reject":
            return "Understood. I’ll close this discussion."
        else:
            return "I see. Let's continue our conversation."
